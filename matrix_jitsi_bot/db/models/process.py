"""The running bot process, and the Jitsi conferences it is currently in.

See :py:class:`~matrix_jitsi_bot.db.models.process.BotProcess` and
:py:class:`~matrix_jitsi_bot.db.models.process.JitsiMonitor`; shown by
``matrix-jitsi-bot status``.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import TYPE_CHECKING

from django.db import models
from django.utils import timezone

if TYPE_CHECKING:
    from matrix_jitsi_bot.jitsi import JitsiStatus

    from .jitsi import JitsiRoom


class AlreadyRunning(ValueError):
    """Another bot process holds this database's
    :py:class:`~matrix_jitsi_bot.db.models.process.RunLock`.
    """


class LockUnavailable(ValueError):
    """The file system can't lock files (some network file systems can't) -
    so nothing would stop two bots running at once.
    """


def account_lock_path(user_id: str) -> Path:
    """The lock file of a Matrix account, in the temporary directory
    every database on this machine shares - see
    :py:class:`~matrix_jitsi_bot.db.models.process.RunLock`.
    """
    import hashlib
    import tempfile

    digest = hashlib.sha256(user_id.encode()).hexdigest()[:16]
    return Path(tempfile.gettempdir()) / f"matrix-jitsi-bot-{digest}.lock"


def lock_path() -> Path:
    """The lock file next to the database - see
    :py:class:`~matrix_jitsi_bot.db.models.process.RunLock`.
    """
    from matrix_jitsi_bot import django as mjb_django

    return Path(f"{mjb_django.db_path()}.lock")


class RunLock:
    """What makes sure only one bot process works on one database: an
    exclusive operating system lock (``flock``) on a lock file next to
    the database, held for as long as the process runs.

    The kernel releases it however the process ends - a crash, ``kill
    -9``, the container being removed, the machine losing power - so it
    can never be left stale, and there is nothing to clean up before a
    new bot can start. Taking it is atomic, so two bots starting at the
    same moment cannot both get it. Whether a bot runs is therefore not
    guessed from process IDs (which containers reuse, e.g. 1) but asked
    of the kernel - see
    :py:meth:`~matrix_jitsi_bot.db.models.process.RunLock.is_held`.

    Another one, per Matrix account (see
    :py:func:`~matrix_jitsi_bot.db.models.process.account_lock_path`),
    stops two databases on this machine from running as the same
    account. That is not covered across machines or containers that
    don't share a temporary directory, and not by a file system without
    working ``flock`` - which is reported, see
    :py:exc:`~matrix_jitsi_bot.db.models.process.LockUnavailable`.
    """

    def __init__(self, path: Path | None = None, *, message: str | None = None) -> None:
        """A lock not held yet - see ``acquire``. ``path`` is the lock
        file (the database's by default), ``message`` what a second
        process is told.
        """
        self._path = path
        self._message = message
        self._file = None

    def acquire(self) -> None:
        """Take the lock.

        Raises:
            AlreadyRunning: another process holds it.
            LockUnavailable: the file system can't lock files.
        """
        import fcntl

        path = self._path or lock_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        file = path.open("a")
        try:
            fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            file.close()
            msg = self._message
            if msg is None:
                pids = [process.pid for process in BotProcess.objects.all()]
                running = f" (process {pids[0]})" if pids else ""
                msg = f"The bot is already running for this database{running}"
            raise AlreadyRunning(msg) from exc
        except OSError as exc:
            file.close()
            msg = (
                f"Cannot lock {path}: {exc.strerror or exc}. Keep the database "
                "on a local file system, or the bot cannot make sure that only "
                "one runs."
            )
            raise LockUnavailable(msg) from exc
        self._file = file

    def release(self) -> None:
        """Give the lock up. Done by the kernel anyway when the process ends."""
        if self._file is not None:
            self._file.close()
            self._file = None

    @staticmethod
    def is_held(path: Path | None = None) -> bool:
        """Whether some process - this one included - holds the lock
        (the database's, unless given ``path``).
        """
        import fcntl

        path = path or lock_path()
        if not path.exists():
            return False
        with path.open("a") as file:
            try:
                fcntl.flock(file, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            except OSError:
                return False
            fcntl.flock(file, fcntl.LOCK_UN)
        return False


class BotProcess(models.Model):
    """A running bot process: what it records about itself after taking
    the :py:class:`~matrix_jitsi_bot.db.models.process.RunLock`.

    Only one may run per database for now. The lock decides whether it
    really does (see
    :py:meth:`~matrix_jitsi_bot.db.models.process.BotProcess.alive`);
    this row says which process it is, for ``matrix-jitsi-bot status``.
    Whoever takes the lock clears out what the previous, interrupted
    process left behind (see
    :py:meth:`~matrix_jitsi_bot.db.models.process.BotProcess.clear`).
    Deleting a process deletes the
    :py:class:`~matrix_jitsi_bot.db.models.process.JitsiMonitor` rows it owns.
    """

    pid = models.IntegerField(help_text="The operating system process ID.")
    secret = models.CharField(
        max_length=64,
        help_text="A random secret this process was started with, telling it "
        "apart from any other, also one with the same process ID.",
    )
    started_at = models.DateTimeField(default=timezone.now)

    def __str__(self) -> str:
        """``pid``."""
        return f"process {self.pid}"

    @classmethod
    def register(cls) -> BotProcess:
        """Record the current process, with a new random secret."""
        return cls.objects.create(pid=os.getpid(), secret=secrets.token_hex(16))

    @classmethod
    def alive(cls) -> list[BotProcess]:
        """The processes that really run: what is recorded while the
        :py:class:`~matrix_jitsi_bot.db.models.process.RunLock` is held,
        else nothing - whatever is recorded is left over from an
        interrupted process. Does not change the database.
        """
        if not RunLock.is_held():
            return []
        return list(cls.objects.all())

    @classmethod
    def clear(cls) -> None:
        """Delete every recorded process, and every monitor with them."""
        cls.objects.all().delete()


class JitsiMonitor(models.Model):
    """A Jitsi conference the bot is in right now, to monitor it - see
    :py:func:`~matrix_jitsi_bot.jitsi.monitor_jitsi_room`.

    Exists only while the connection is open: deleted again when the bot
    leaves the conference.
    """

    jitsi_room = models.OneToOneField(
        "matrix_jitsi_bot.JitsiRoom", on_delete=models.CASCADE, related_name="monitor"
    )
    process = models.ForeignKey(
        BotProcess,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="monitors",
        help_text="The process holding the connection.",
    )
    started_at = models.DateTimeField(default=timezone.now)
    last_state_at = models.DateTimeField(
        null=True, blank=True, help_text="When the conference last changed."
    )
    attempts = models.IntegerField(
        default=0, help_text="Reconnect attempts since the connection was lost."
    )

    def __str__(self) -> str:
        """The monitored conference's URL."""
        return f"monitoring {self.jitsi_room.url}"

    @classmethod
    def begin(cls, jitsi_room: JitsiRoom, process: BotProcess | None) -> JitsiMonitor:
        """Record that ``process`` is now in ``jitsi_room``'s conference."""
        monitor, _created = cls.objects.update_or_create(
            jitsi_room=jitsi_room,
            defaults={
                "process": process,
                "started_at": timezone.now(),
                "last_state_at": None,
                "attempts": 0,
            },
        )
        return monitor

    def record(self, status: JitsiStatus) -> None:
        """Note that the conference just reported ``status``."""
        self.last_state_at = timezone.now()
        self.attempts = status.attempts
        self.save(update_fields=["last_state_at", "attempts"])

    @classmethod
    def is_active(cls, jitsi_room: JitsiRoom) -> bool:
        """Whether a running bot is in ``jitsi_room``'s conference right
        now - its status in the database is then always current.
        """
        monitor = cls.objects.filter(jitsi_room=jitsi_room).first()
        if monitor is None:
            return False
        return monitor.process_id is None or any(
            process.pk == monitor.process_id for process in BotProcess.alive()
        )

    @classmethod
    def end(cls, jitsi_room: JitsiRoom) -> None:
        """Record that the bot left ``jitsi_room``'s conference."""
        cls.objects.filter(jitsi_room=jitsi_room).delete()
