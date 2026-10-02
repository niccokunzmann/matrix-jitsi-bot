"""Programmatic interface to the Matrix Jitsi Bot.

``cli.py`` is a thin command-line wrapper around
:py:class:`~matrix_jitsi_bot.bot.MatrixJitsiBot` - anything it can do
can also be done directly from Python.
"""

from __future__ import annotations

import functools
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from . import django as mjb_django
from .matrix_login import (
    LoginCheckResult,
    check_login,
    has_cross_signing,
    homeserver_from_user_id,
    set_avatar,
    set_display_name,
)

if TYPE_CHECKING:
    import asyncio
    from datetime import datetime
    from pathlib import Path

    import nio
    import niobot

    from .db.models import Account
    from .icon.merge import IconMerge
    from .interactions import BotInteraction

logger = logging.getLogger(__name__)


@dataclass
class TrackedRoomStatus:
    """One Jitsi conference's last-known status, as tracked in one room
    - part of a :py:class:`~matrix_jitsi_bot.bot.RoomStatus`, see
    :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.status_report`.
    """

    url: str
    is_open: bool
    last_checked_at: datetime | None
    last_opened_at: datetime | None
    next_check_at: datetime
    track_open: bool
    track_close: bool
    track_starts: bool
    track_joins: bool
    track_leaves: bool


@dataclass
class RoomStatus:
    """A DB-only snapshot of one room the bot is in - see
    :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.status_report`.
    """

    room_id: str
    label: str
    moderators: list[str]
    last_message_at: datetime | None
    tracked: list[TrackedRoomStatus] = field(default_factory=list)


@dataclass
class AccountStatus:
    """Every room one configured account is in - see
    :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.status_report`.

    ``user_id`` is ``None`` for rooms whose
    :py:attr:`~matrix_jitsi_bot.db.models.room.Room.account` isn't set
    - from before that field existed, or a room
    :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.reconcile_joined_rooms`
    hasn't revisited yet - grouped together rather than lost.
    """

    user_id: str | None
    rooms: list[RoomStatus] = field(default_factory=list)


@dataclass
class MonitoredStatus:
    """A Jitsi conference the bot is in right now - see
    :py:class:`~matrix_jitsi_bot.db.models.process.JitsiMonitor` and
    :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.process_report`.
    """

    url: str
    started_at: datetime
    last_state_at: datetime | None
    attempts: int
    participants: list[str]


@dataclass
class ProcessStatus:
    """A running bot process - see
    :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.process_report`.
    """

    pid: int
    started_at: datetime


@dataclass
class ProcessReport:
    """The running bot processes and what they monitor - see
    :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.process_report`.
    """

    processes: list[ProcessStatus] = field(default_factory=list)
    monitored: list[MonitoredStatus] = field(default_factory=list)


class _Locks:
    """Every :py:class:`~matrix_jitsi_bot.db.models.process.RunLock` a
    running bot holds - see
    :py:func:`~matrix_jitsi_bot.bot._acquire_locks`.
    """

    def __init__(self, locks) -> None:
        """Hold ``locks``."""
        self._locks = locks

    def release(self) -> None:
        """Give every lock up."""
        for lock in self._locks:
            lock.release()


def _acquire_locks(account: Account) -> _Locks:
    """Take the
    :py:class:`~matrix_jitsi_bot.db.models.process.RunLock` of this
    database, and of ``account`` - so no other database on this machine
    runs as it too. All or none.

    Raises:
        matrix_jitsi_bot.db.models.process.AlreadyRunning: a bot is
            already running.
        matrix_jitsi_bot.db.models.process.LockUnavailable: the file
            system can't lock files.
    """
    from .db.models import RunLock
    from .db.models.process import account_lock_path

    database = RunLock()
    database.acquire()
    account_lock = RunLock(
        account_lock_path(account.user_id),
        message=(
            f"The bot is already running as {account.user_id} "
            "for another database on this machine"
        ),
    )
    try:
        account_lock.acquire()
    except PermissionError:
        # Someone else's file in a shared temporary directory: this
        # extra protection isn't available, the database's own still is.
        return _Locks([database])
    except BaseException:
        database.release()
        raise
    return _Locks([database, account_lock])


def _log_errors(func):
    """Wrap an async nio event callback so an exception in it is logged
    instead of propagating.

    nio's own sync loop keeps running regardless, but an unhandled
    exception here would otherwise silently drop that one event and any
    reply it should have gotten - this way ``run``'s loop survives a
    bug in a single event, room, or
    :py:class:`~matrix_jitsi_bot.interactions.base.BotInteraction`, and
    the error is visible in the logs (see ``-v``/``-vv``) instead of
    vanishing.
    """

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        """Run ``func``, logging (rather than propagating) any exception."""
        try:
            return await func(*args, **kwargs)
        except Exception:
            logger.exception("Error handling a Matrix event")
            return None

    return wrapper


class MatrixJitsiBot:
    """Manage Matrix accounts, the database, and run the bot.

    Reacts to messages in rooms it has joined via a single
    ``interaction`` -
    :py:class:`~matrix_jitsi_bot.interactions.all.AllInteractions`
    (every built-in command) by default, or pass a different
    :py:class:`~matrix_jitsi_bot.interactions.base.BotInteraction` to
    run with another set instead.
    """

    def __init__(self, interaction: BotInteraction | None = None) -> None:
        """Configure Django (see
        :py:func:`~matrix_jitsi_bot.django.setup_django`) and store
        ``interaction`` (defaulting to
        :py:class:`~matrix_jitsi_bot.interactions.all.AllInteractions`).
        """
        mjb_django.setup_django()
        if interaction is None:
            from .interactions import AllInteractions

            interaction = AllInteractions()
        self.interaction = interaction
        #: The running
        #: :py:meth:`~matrix_jitsi_bot.db.models.jitsi.JitsiRoom.monitor_and_notify`
        #: task of every Jitsi conference being monitored by staying in
        #: it, by URL - see
        #: :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.poll_jitsi_rooms_once`.
        self._monitors: dict[str, asyncio.Task] = {}
        #: This process's own
        #: :py:class:`~matrix_jitsi_bot.db.models.process.BotProcess`
        #: record while
        #: :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.run` runs.
        self._process = None
        self._lock = None
        #: When (``time.monotonic()``) a room whose avatar change
        #: failed may be tried again, by room ID.
        self._speaker_retry_at: dict[str, float] = {}
        #: The same for a status message that could not be edited, by
        #: the event ID of the message.
        self._status_retry_at: dict[str, float] = {}
        #: Draw the speaker on the avatar of a chat, or of a space, or the
        #: whole speaker for a room without one - see
        #: :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot._show_speaker`.
        #: Tests set others, e.g. to change nothing visible.
        from .icon.merge import RoomSpeaker, SpaceSpeaker, SpeakerFull

        self.merger_with_avatar: IconMerge = RoomSpeaker()
        self.merger_space_with_avatar: IconMerge = SpaceSpeaker()
        self.merger_without_avatar: IconMerge = SpeakerFull()

    # -- accounts ----------------------------------------------------------

    async def create_account(
        self,
        user_id: str,
        *,
        homeserver: str = "",
        device_id: str = "",
        password: str = "",
        access_token: str = "",
        test: bool = True,
    ) -> tuple[Account, bool]:
        """Create or update a Matrix account the bot can log in as.

        ``homeserver`` defaults to a guess from ``user_id``'s server
        name - see
        :py:func:`~matrix_jitsi_bot.matrix_login.homeserver_from_user_id`
        - pass it explicitly if that homeserver delegates its
        client-server API elsewhere.

        Unless ``test`` is ``False``, the credentials are first
        verified against the homeserver;
        :py:exc:`~matrix_jitsi_bot.matrix_login.LoginFailed` propagates
        if that fails and nothing is saved.

        Returns the account and whether it was newly created.
        """
        from asgiref.sync import sync_to_async

        from .db.models import Account

        if not homeserver:
            homeserver = homeserver_from_user_id(user_id)

        if test:
            result = await check_login(
                homeserver=homeserver,
                user_id=user_id,
                password=password,
                access_token=access_token,
                device_id=device_id,
            )
            device_id = result.device_id or device_id
            access_token = result.access_token or access_token

        return await sync_to_async(Account.objects.update_or_create)(
            user_id=user_id,
            defaults={
                "homeserver": homeserver,
                "device_id": device_id,
                "password": password,
                "access_token": access_token,
            },
        )

    def list_accounts(self) -> list[Account]:
        """Every configured account, ordered by Matrix user ID."""
        from .db.models import Account

        return list(Account.objects.order_by("user_id"))

    def get_account(self, user_id: str) -> Account:
        """Look up an account. Raises ``Account.DoesNotExist`` if there is none."""
        from .db.models import Account

        return Account.objects.get(user_id=user_id)

    def remove_account(self, user_id: str) -> bool:
        """Remove an account. Returns whether one was actually removed."""
        from .db.models import Account

        deleted, _ = Account.objects.filter(user_id=user_id).delete()
        return bool(deleted)

    def set_account_password(self, user_id: str, password: str) -> Account:
        """Update the stored password for the account with ``user_id``."""
        account = self.get_account(user_id)
        account.password = password
        account.save(update_fields=["password"])
        return account

    def set_account_access_token(self, user_id: str, access_token: str) -> Account:
        """Update the stored access token for the account with ``user_id``."""
        account = self.get_account(user_id)
        account.access_token = access_token
        account.save(update_fields=["access_token"])
        return account

    def set_account_homeserver(self, user_id: str, homeserver: str) -> Account:
        """Update the stored homeserver URL for the account with ``user_id``."""
        account = self.get_account(user_id)
        account.homeserver = homeserver
        account.save(update_fields=["homeserver"])
        return account

    def set_account_device_id(self, user_id: str, device_id: str) -> Account:
        """Update the stored device ID for the account with ``user_id``."""
        account = self.get_account(user_id)
        account.device_id = device_id
        account.save(update_fields=["device_id"])
        return account

    async def check_account(self, user_id: str) -> LoginCheckResult:
        """Verify a saved account can still log in. Raises
        :py:exc:`~matrix_jitsi_bot.matrix_login.LoginFailed` if not.
        """
        from asgiref.sync import sync_to_async

        account = await sync_to_async(self.get_account)(user_id)
        return await check_login(
            homeserver=account.homeserver,
            user_id=account.user_id,
            password=account.password,
            access_token=account.access_token,
            device_id=account.device_id,
        )

    async def check_account_cross_signing(self, user_id: str) -> bool:
        """Whether the account has a cross-signing identity set up on
        its homeserver - see
        :py:func:`~matrix_jitsi_bot.matrix_login.has_cross_signing`
        for what that means and why the bot can't set one up itself.

        Best-effort: returns ``True`` (no warning) if the check itself
        fails for any reason (network error, unsupported homeserver
        endpoint, ...) rather than blocking
        :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.check_account`
        on a diagnostic-only lookup that isn't what that command is
        primarily for.
        """
        from asgiref.sync import sync_to_async

        account = await sync_to_async(self.get_account)(user_id)
        try:
            return await has_cross_signing(
                homeserver=account.homeserver,
                user_id=account.user_id,
                password=account.password,
                access_token=account.access_token,
                device_id=account.device_id,
            )
        except Exception:
            logger.exception(
                "Could not check cross-signing status for %s", account.user_id
            )
            return True

    async def set_account_display_name(self, user_id: str, display_name: str) -> None:
        """Set the account's Matrix profile display name - see
        :py:func:`~matrix_jitsi_bot.matrix_login.set_display_name` -
        and store it on the account in the database (see
        :py:meth:`~matrix_jitsi_bot.db.models.account.Account.update_display_name`),
        so it's disclosed whenever
        :py:func:`~matrix_jitsi_bot.jitsi.check_jitsi_room` briefly
        joins a Jitsi conference to inspect it, without waiting for a
        running bot to notice the change itself. Raises
        :py:exc:`~matrix_jitsi_bot.matrix_login.LoginFailed` if login
        fails - the database is left untouched in that case.
        """
        from asgiref.sync import sync_to_async

        account = await sync_to_async(self.get_account)(user_id)
        await set_display_name(
            homeserver=account.homeserver,
            user_id=account.user_id,
            password=account.password,
            access_token=account.access_token,
            device_id=account.device_id,
            display_name=display_name,
        )
        await sync_to_async(account.update_display_name)(display_name)

    async def set_account_avatar(self, user_id: str, image: Path | str) -> None:
        """Set the account's Matrix profile avatar ("logo") - see
        :py:func:`~matrix_jitsi_bot.matrix_login.set_avatar`. ``image``
        is the path of an image file, or a web address (``http://`` or
        ``https://``) to download it from first - see
        :py:func:`~matrix_jitsi_bot.image.download_image`.

        Raises :py:exc:`~matrix_jitsi_bot.matrix_login.LoginFailed` if
        login or the upload fails, and
        :py:exc:`~matrix_jitsi_bot.image.DownloadFailed` if the image
        cannot be downloaded.
        """
        import asyncio
        import tempfile
        from pathlib import Path

        from asgiref.sync import sync_to_async

        from .image import download_image, is_url

        account = await sync_to_async(self.get_account)(user_id)
        with tempfile.TemporaryDirectory() as directory:
            if isinstance(image, str) and is_url(image):
                image = await download_image(image, Path(directory))
            mxc = await set_avatar(
                homeserver=account.homeserver,
                user_id=account.user_id,
                password=account.password,
                access_token=account.access_token,
                device_id=account.device_id,
                image_path=Path(image),
            )
            await self._store_avatar_for_jitsi(
                account, mxc, await asyncio.to_thread(Path(image).read_bytes)
            )

    @staticmethod
    async def _store_avatar_for_jitsi(
        account: Account, mxc: str | None, image: bytes | None
    ) -> None:
        """Store ``image`` - the profile avatar of ``account``, which has
        the content URI ``mxc`` - as what is disclosed as its avatar when
        it joins a Jitsi conference, see
        :py:meth:`~matrix_jitsi_bot.db.models.account.Account.jitsi_avatar_of`.
        An image that cannot be used is logged, and the logo disclosed.
        """
        import asyncio

        from asgiref.sync import sync_to_async

        from .image import avatar_data_uri, shrink_avatar

        data_uri = None
        if image:
            try:
                data_uri = avatar_data_uri(
                    await asyncio.to_thread(shrink_avatar, image)
                )
            except ValueError as exc:
                logger.warning(
                    "The avatar of %s cannot be shown in Jitsi: %s",
                    account.user_id,
                    exc,
                )
        await sync_to_async(account.update_avatar)(mxc, data_uri)
        logger.info(
            "%s discloses %s as its avatar in Jitsi conferences",
            account.user_id,
            "its profile avatar" if data_uri else "the logo",
        )

    # -- database ------------------------------------------------------------

    def migrate(self) -> None:
        """Apply database migrations."""
        mjb_django.migrate()

    def makemigrations(self) -> None:
        """Generate new database migrations for model changes."""
        mjb_django.makemigrations()

    def db_path(self) -> Path:
        """The path of the database currently configured in Django settings."""
        return mjb_django.db_path()

    def backup(self, file: Path) -> Path:
        """Back up the database to ``file``. Returns the resolved destination path."""
        return mjb_django.backup(file)

    def restore(self, file: Path) -> Path:
        """Restore the database from ``file``.

        Raises ``FileNotFoundError`` if missing.
        """
        return mjb_django.restore(file)

    # -- status ----------------------------------------------------------------

    def status_report(self) -> list[AccountStatus]:
        """A DB-only snapshot of every room the bot is in, grouped by
        account and - within each account - latest message first, what
        ``matrix-jitsi-bot status`` shows. No network access; Jitsi
        conference status is exactly as last observed by ``run``'s
        background polling (see :py:mod:`matrix_jitsi_bot.jitsi`).

        Includes rooms with no
        :py:class:`~matrix_jitsi_bot.db.models.conversation.Conversation`
        yet (nothing said in them since the bot joined) - it's only
        created lazily, on the first message. Every configured
        :py:class:`~matrix_jitsi_bot.db.models.account.Account` gets an
        entry even with zero rooms; a room whose
        :py:attr:`~matrix_jitsi_bot.db.models.room.Room.account` isn't
        set groups under a trailing ``user_id=None`` entry instead of
        being dropped - see
        :py:class:`~matrix_jitsi_bot.bot.AccountStatus`.
        """
        from datetime import UTC, datetime

        from .db.models import Account, Room

        never = datetime.min.replace(tzinfo=UTC)
        rooms = Room.objects.select_related("conversation", "account").prefetch_related(
            "members", "tracked_jitsi_rooms__jitsi_room"
        )

        by_account: dict[str | None, list[RoomStatus]] = {}
        for room in rooms:
            report = RoomStatus(
                room_id=room.room_id,
                label=room.label(),
                moderators=room.moderators(),
                last_message_at=(
                    conversation.last_message.server_timestamp
                    if (conversation := getattr(room, "conversation", None))
                    and conversation.last_message
                    else None
                ),
                tracked=[
                    TrackedRoomStatus(
                        url=tracked.jitsi_room.url,
                        is_open=tracked.jitsi_room.is_open,
                        last_checked_at=tracked.jitsi_room.last_checked_at,
                        last_opened_at=tracked.jitsi_room.last_opened_at,
                        next_check_at=tracked.jitsi_room.next_check_at,
                        track_open=tracked.track_open,
                        track_close=tracked.track_close,
                        track_starts=tracked.track_starts,
                        track_joins=tracked.track_joins,
                        track_leaves=tracked.track_leaves,
                    )
                    for tracked in room.tracked_jitsi_rooms.all()
                ],
            )
            key = room.account.user_id if room.account else None
            by_account.setdefault(key, []).append(report)

        for room_reports in by_account.values():
            room_reports.sort(key=lambda r: r.last_message_at or never, reverse=True)

        account_ids = Account.objects.order_by("user_id").values_list(
            "user_id", flat=True
        )
        reports = [
            AccountStatus(user_id=user_id, rooms=by_account.pop(user_id, []))
            for user_id in account_ids
        ]
        reports.extend(
            AccountStatus(user_id=user_id, rooms=room_reports)
            for user_id, room_reports in by_account.items()
        )
        return reports

    def process_report(self) -> ProcessReport:
        """The bot processes running for this database, and the Jitsi
        conferences they are in right now (see
        :py:class:`~matrix_jitsi_bot.db.models.process.JitsiMonitor`),
        what ``matrix-jitsi-bot status`` shows. DB-only, and it ignores
        what an interrupted process left behind - see
        :py:meth:`~matrix_jitsi_bot.db.models.process.BotProcess.alive`.
        """
        from .db.models import BotProcess, JitsiMonitor

        alive = BotProcess.alive()
        alive_ids = {process.pk for process in alive}
        monitors = JitsiMonitor.objects.select_related("jitsi_room").order_by(
            "jitsi_room__url"
        )
        return ProcessReport(
            processes=[
                ProcessStatus(pid=process.pid, started_at=process.started_at)
                for process in alive
            ],
            monitored=[
                MonitoredStatus(
                    url=monitor.jitsi_room.url,
                    started_at=monitor.started_at,
                    last_state_at=monitor.last_state_at,
                    attempts=monitor.attempts,
                    participants=list(monitor.jitsi_room.participants),
                )
                for monitor in monitors
                if monitor.process_id is None or monitor.process_id in alive_ids
            ],
        )

    # -- running -------------------------------------------------------------

    async def run(self, user_id: str | None = None, wait: float | None = None) -> None:
        """Log in and run the bot's main loop until interrupted.

        Uses the only configured account if ``user_id`` is omitted;
        raises :py:exc:`ValueError` if that's ambiguous (zero or
        multiple accounts).

        ``wait`` is how often, in seconds, to check whether any tracked
        Jitsi conference is due a check (see
        :py:mod:`matrix_jitsi_bot.jitsi`) - defaults to the
        ``MJB_POLL_INTERVAL`` environment variable, or 1.
        """
        from asgiref.sync import sync_to_async

        if wait is None:
            import os

            wait = float(os.environ.get("MJB_POLL_INTERVAL", "1"))

        if user_id is None:
            accounts = await sync_to_async(self.list_accounts)()
            if len(accounts) != 1:
                raise ValueError(
                    "No accounts configured, run `matrix-jitsi-bot account create`"
                    if not accounts
                    else "Multiple accounts configured, specify which user ID to run as"
                )
            account = accounts[0]
        else:
            account = await sync_to_async(self.get_account)(user_id)

        logger.info("Running as %s", account.user_id)
        await sync_to_async(self._register_process)(account)
        try:
            await self._run_client(account, wait)
        finally:
            process, self._process = self._process, None
            await sync_to_async(process.delete)()
            self._lock.release()

    def _register_process(self, account: Account) -> None:
        """Take the
        :py:class:`~matrix_jitsi_bot.db.models.process.RunLock` and
        record this process as the running one - see
        :py:class:`~matrix_jitsi_bot.db.models.process.BotProcess`.

        Only one process may run per database: raises
        :py:exc:`~matrix_jitsi_bot.db.models.process.AlreadyRunning`
        (a :py:exc:`ValueError`) if another one holds the lock. Since
        holding it means no other one runs, whatever an interrupted
        process left in the database is cleared out.
        """
        from .db.models import BotProcess

        lock = _acquire_locks(account)
        self._lock = lock
        try:
            BotProcess.clear()
            self._process = BotProcess.register()
        except BaseException:
            lock.release()
            raise

    async def run_once(self, user_id: str | None = None) -> int:
        """Log in, check *every* tracked Jitsi conference once -
        regardless of whether it's currently due, see
        :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.poll_jitsi_rooms_all`
        - notify about anything that changed, then disconnect. Returns
        how many conferences were checked.

        Unlike :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.run`,
        which keeps going forever, this is for one-shot invocations - a
        cron job, or wanting confirmation that everything was actually
        queried rather than just whatever happened to be due -
        ``matrix-jitsi-bot run --once``. Uses the only configured
        account if ``user_id`` is omitted; raises :py:exc:`ValueError`
        if that's ambiguous, same as
        :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.run`.
        """

        from asgiref.sync import sync_to_async

        if user_id is None:
            accounts = await sync_to_async(self.list_accounts)()
            if len(accounts) != 1:
                raise ValueError(
                    "No accounts configured, run `matrix-jitsi-bot account create`"
                    if not accounts
                    else "Multiple accounts configured, specify which user ID to run as"
                )
            account = accounts[0]
        else:
            account = await sync_to_async(self.get_account)(user_id)

        # Not next to a running bot - it would announce everything twice.
        lock = await sync_to_async(_acquire_locks)(account)

        try:
            return await self._run_once_as(account)
        finally:
            lock.release()

    async def _run_once_as(self, account: Account) -> int:
        """The body of
        :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.run_once`, once it
        has the :py:class:`~matrix_jitsi_bot.db.models.process.RunLock`.
        """
        import asyncio
        import contextlib

        logger.info("Running once as %s", account.user_id)

        client, reconciled = self._build_client(account)
        start_task = asyncio.create_task(self._start_client(client, account))
        ready_task = asyncio.create_task(reconciled.wait())
        try:
            done, _pending = await asyncio.wait(
                {start_task, ready_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if start_task in done:
                # start() only ever finishes early by raising - re-raise why.
                start_task.result()
                raise RuntimeError(
                    "Matrix client stopped before its first sync completed."
                )
            return await self.poll_jitsi_rooms_all(client)
        finally:
            start_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await start_task
            with contextlib.suppress(Exception):
                await client.close()

    async def _run_client(self, account: Account, wait: float) -> None:
        """Log in as ``account`` and run the Matrix client and Jitsi
        polling loop side by side, until the client stops.
        """
        import asyncio
        import contextlib

        client, _reconciled = self._build_client(account)
        poll_task = asyncio.create_task(self.poll_jitsi_rooms_forever(client, wait))
        try:
            await self._start_client(client, account)
        finally:
            poll_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await poll_task
            # Also when starting failed: otherwise its HTTP session is left open.
            with contextlib.suppress(Exception):
                await client.close()

    def _build_client(self, account: Account) -> tuple[niobot.NioBot, asyncio.Event]:
        """Construct a niobot client wired up with every event callback
        the bot needs (invites, member sync, room renames, messages), end-to-end
        encryption support (see
        :py:func:`~matrix_jitsi_bot.django.crypto_store_path`), and a
        one-shot room reconciliation on its first sync (see
        :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.reconcile_joined_rooms`)
        - shared by
        :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot._run_client` and
        :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.run_once`.

        Returns the client, and an
        :py:class:`asyncio.Event` set once that first-sync
        reconciliation has run.
        """
        import asyncio

        import nio
        import niobot

        client = niobot.NioBot(
            homeserver=account.homeserver,
            user_id=account.user_id,
            device_id=account.device_id or "matrix-jitsi-bot",
            command_prefix="!",
            # Without a store, an encrypted room's messages arrive only as
            # an undecryptable `nio.MegolmEvent` - niobot auto-enables
            # encryption support once given this (see
            # `matrix_jitsi_bot.django.crypto_store_path`).
            store_path=str(mjb_django.crypto_store_path()),
        )
        _add_invite_handler(client, account)
        client.add_event_callback(
            lambda room, event: _sync_room_members(account, room, event),
            nio.RoomMemberEvent,
        )
        client.add_event_callback(
            lambda _room, event: _refresh_own_avatar(client, account, event),
            nio.RoomMemberEvent,
        )
        client.add_event_callback(_sync_room_name, nio.RoomNameEvent)
        client.add_event_callback(_forget_deleted_status_message, nio.RedactionEvent)
        client.add_event_callback(
            lambda room, event: self.interaction.on_matrix_message(client, room, event),
            nio.RoomMessageText,
        )

        reconciled = asyncio.Event()

        async def _reconcile_once(_response: nio.SyncResponse) -> None:
            """Run ``reconcile_joined_rooms`` and
            ``_sync_own_display_name`` once, on the first sync response
            only - see their own docstrings for why.
            """
            if reconciled.is_set():
                return
            await self._sync_own_display_name(client, account)
            await self.sync_own_avatar(client, account)
            await self.reconcile_joined_rooms(client, account)
            reconciled.set()

        client.add_response_callback(_reconcile_once, nio.SyncResponse)
        client.add_response_callback(_forget_left_rooms, nio.SyncResponse)
        return client, reconciled

    @staticmethod
    async def _start_client(client: niobot.NioBot, account: Account) -> None:
        """Log ``client`` in - by password or access token, whichever
        ``account`` has - and run its sync loop until stopped. Shared
        by
        :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot._run_client` and
        :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.run_once`.
        """
        if account.access_token:
            await client.start(access_token=account.access_token)
        else:
            await client.start(password=account.password)

    @staticmethod
    async def _sync_own_display_name(client: niobot.NioBot, account: Account) -> None:
        """Fetch this account's Matrix profile display name and store
        it on ``account`` in the database (see
        :py:meth:`~matrix_jitsi_bot.db.models.account.Account.update_display_name`),
        so :py:func:`~matrix_jitsi_bot.jitsi.check_jitsi_room` can
        disclose it while briefly joining a Jitsi conference to
        inspect it - see
        :py:meth:`~matrix_jitsi_bot.db.models.jitsi.JitsiRoom.check_and_notify`.

        Run once at startup, in case the display name last changed
        by some other means (directly on the homeserver, or a
        previous run that never got to see it) - kept up to date
        afterwards by :py:func:`~matrix_jitsi_bot.bot._sync_room_members`,
        whenever a membership event reports this account's own
        display name changing. Nothing is cached in this process
        itself: every check reads ``account.display_name`` fresh from
        the database (see
        :py:meth:`~matrix_jitsi_bot.db.models.account.Account.display_name_of`),
        so it can also be changed from outside this process while the
        bot is running.

        Logged, not raised, if the lookup fails - falling back to
        disclosing no name is harmless.
        """
        import nio
        from asgiref.sync import sync_to_async

        response = await client.get_displayname()
        if isinstance(response, nio.ProfileGetDisplayNameError):
            logger.warning("Could not fetch this account's display name: %s", response)
            return
        await sync_to_async(account.update_display_name)(response.displayname)

    @staticmethod
    async def sync_own_avatar(client: niobot.NioBot, account: Account) -> None:
        """Fetch this account's Matrix profile avatar and store what is
        disclosed as its avatar when it joins a Jitsi conference - see
        :py:meth:`~matrix_jitsi_bot.db.models.account.Account.jitsi_avatar_of`:
        the avatar, shrunk, or the logo if it has none.

        Run once at startup, and again whenever a membership event
        shows the avatar changed - see
        :py:func:`~matrix_jitsi_bot.bot._refresh_own_avatar`. Nothing is
        downloaded while the avatar is the one already stored. Logged,
        not raised, if the avatar cannot be fetched: what is stored stays.
        """
        import nio
        from asgiref.sync import sync_to_async

        await sync_to_async(account.refresh_from_db)()
        response = await client.get_avatar()
        if isinstance(response, nio.ProfileGetAvatarError):
            logger.warning("Could not fetch this account's avatar: %s", response)
            return
        mxc = response.avatar_url or ""
        if mxc == account.avatar_mxc and (account.avatar_data_uri or not mxc):
            return
        image = None
        if mxc:
            download = await client.download(mxc=mxc)
            if isinstance(download, nio.DownloadError):
                logger.warning("Could not download the avatar %s: %s", mxc, download)
                return
            image = download.body
        await MatrixJitsiBot._store_avatar_for_jitsi(account, mxc, image)

    @staticmethod
    async def reconcile_joined_rooms(client: niobot.NioBot, account: Account) -> None:
        """Make sure the database matches ``client.rooms`` (populated by
        the client's first sync) exactly, for ``account``: creates -
        and announces, see
        :py:data:`~matrix_jitsi_bot.bot._NEEDS_CONFIGURATION_MESSAGE` -
        a :py:class:`~matrix_jitsi_bot.db.models.room.Room` row for any
        joined room missing one, tagging every one with ``account``
        (see
        :py:meth:`~matrix_jitsi_bot.db.models.room.Room.ensure_account`)
        if it isn't tagged already; and forgets (see
        :py:meth:`~matrix_jitsi_bot.db.models.room.Room.forget_others`)
        any room tagged to ``account`` that isn't actually joined
        anymore.

        Run once, at the start of every
        :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.run`/
        :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.run_once` - the
        forgetting half specifically covers being removed from a room
        (kicked, banned, or otherwise) while the bot *wasn't* running
        to see the live membership change - see
        :py:func:`~matrix_jitsi_bot.bot._forget_left_rooms` for the
        equivalent while it is. Recovering a *missing* row similarly
        doesn't need the bot to have been running for the invite - it
        just needs a fresh sync to see what's currently joined. Either
        way, any lost *configuration* (tracked conferences, pause
        state) is gone for good along with its row; only bare
        existence is restored or removed. A ``staticmethod``: called
        from a client callback that has no
        :py:class:`~matrix_jitsi_bot.bot.MatrixJitsiBot` instance of
        its own.
        """
        from asgiref.sync import sync_to_async

        from .db.models import Room

        joined_room_ids = list(client.rooms)
        for room_id in joined_room_ids:
            if _is_space(client.rooms[room_id]):
                continue
            room, created = await sync_to_async(Room.objects.get_or_create)(
                room_id=room_id
            )
            await sync_to_async(room.ensure_account)(account)
            await sync_to_async(room.update_name)(client.rooms[room_id].name)
            if created:
                logger.info("Recreated room %s in the database", room_id)
                await client.send_message(room_id, _NEEDS_CONFIGURATION_MESSAGE)

        forgotten = await sync_to_async(Room.forget_others)(account, joined_room_ids)
        for room_id in forgotten:
            logger.info("No longer in room %s - forgetting it", room_id)

    @staticmethod
    async def leave_if_flagged(client: niobot.NioBot, room_id: str) -> None:
        """Act on
        :py:attr:`~matrix_jitsi_bot.db.models.room.Room.should_leave`
        (see
        :py:class:`~matrix_jitsi_bot.interactions.room.RoomInteraction`).

        Leaves the Matrix room first, then deletes its
        :py:class:`~matrix_jitsi_bot.db.models.room.Room` row - in that
        order, so a failed ``room_leave`` call leaves the flag set to
        retry next time, rather than forgetting the room without having
        left it. If the room shows the speaker on its avatar (see
        :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.update_speaker_avatars`),
        the original avatar is put back first, as it would be lost with
        the row - leaving anyway if that fails. A ``staticmethod``: called from
        :py:meth:`~matrix_jitsi_bot.interactions.base.BotInteraction.on_matrix_message`,
        which has no
        :py:class:`~matrix_jitsi_bot.bot.MatrixJitsiBot` instance of
        its own to call this on.
        """
        from asgiref.sync import sync_to_async

        from .db.models import Room

        if not await sync_to_async(Room.is_flagged_to_leave)(room_id):
            return
        room = await sync_to_async(Room.objects.filter(room_id=room_id).first)()
        if room is not None and room.speaker_shown:
            # The cached original is deleted with the room: put it back first.
            try:
                await MatrixJitsiBot._restore_avatar(client, room)
            except Exception:
                logger.exception("Could not restore the avatar of %s", room_id)
        logger.info("Leaving room %s", room_id)
        await client.room_leave(room_id)
        await sync_to_async(Room.forget)(room_id)

    async def poll_jitsi_rooms_once(self, client) -> None:
        """Check every currently-due
        :py:class:`~matrix_jitsi_bot.db.models.jitsi.JitsiRoom` once -
        see
        :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot._check_jitsi_rooms`.

        A conference found open that some tracker wants joins or
        leaves of (see
        :py:meth:`~matrix_jitsi_bot.db.models.jitsi.JitsiRoom.wants_monitoring`)
        is then monitored by staying in it, instead of being checked
        again at intervals - until it is closed, or nobody wants those
        anymore. Conferences being monitored are never due for a check
        meanwhile.
        """
        from asgiref.sync import sync_to_async

        from .db.models import JitsiRoom

        await self._stop_unwanted_monitors()
        due = [
            jitsi_room
            for jitsi_room in await sync_to_async(JitsiRoom.due)()
            if jitsi_room.url not in self._monitors
        ]
        await self._check_jitsi_rooms(client, due)
        for jitsi_room in due:
            if await sync_to_async(jitsi_room.wants_monitoring)():
                self._start_monitor(client, jitsi_room)
        await self.update_speaker_avatars(client)
        await self.update_status_messages(client)

    async def update_status_messages(self, client) -> None:
        """Edit every status message of the chats of ``client``'s account
        that does not say what the conferences tracked there are doing now
        (see :py:class:`~matrix_jitsi_bot.db.models.status_message.StatusMessage`).

        This looks at the database and nothing else, so it catches every
        reason for a change: a conference that opens or closes, one that is
        added or removed, a chat that is unpaused. A paused chat is left
        alone. A message that cannot be edited is tried again after
        :py:data:`~matrix_jitsi_bot.bot._STATUS_RETRY` seconds.
        """
        import time

        from asgiref.sync import sync_to_async

        from .db.models import Account, StatusMessage

        if not getattr(client, "next_batch", True):
            return
        account = await sync_to_async(
            Account.objects.filter(user_id=client.user_id).first
        )()
        if account is None:
            return
        for message, text in await sync_to_async(StatusMessage.outdated)(account):
            if self._status_retry_at.get(message.event_id, 0) > time.monotonic():
                continue
            try:
                await client.edit_message(message.room.room_id, message.event_id, text)
                message.text = text
                await sync_to_async(message.save)(update_fields=["text"])
                self._status_retry_at.pop(message.event_id, None)
            except Exception:
                logger.exception(
                    "Could not edit the status message of %s", message.room.room_id
                )
                self._status_retry_at[message.event_id] = (
                    time.monotonic() + _STATUS_RETRY
                )

    async def update_speaker_avatars(self, client) -> None:
        """Show the speaker overlay (see
        :py:class:`~matrix_jitsi_bot.icon.merge.SpeakerTopRight`) on the
        avatar of every room of ``client``'s account that wants it (see
        :py:meth:`~matrix_jitsi_bot.db.models.room.Room.wants_speaker`),
        and restore the avatar of every room that no longer does.

        The avatar the room had is downloaded and cached in the database
        first (see :py:meth:`~matrix_jitsi_bot.db.models.room.Room.cache_avatar`),
        and removed from it again once restored. A failure is logged and
        retried after :py:data:`~matrix_jitsi_bot.bot._SPEAKER_RETRY`
        seconds. Nothing happens in a room where the bot may not change
        the avatar, nor before ``client`` has synced for the first time.
        That is how a bot that was stopped while it showed the speaker
        puts the avatars back right after it is started again. A space
        is asked of the homeserver, see
        :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot._avatar_state`.
        """
        import time

        from asgiref.sync import sync_to_async

        from .db.models import Account, Room, Space

        if not getattr(client, "next_batch", True):
            # Not synced yet: it knows no room, and an attempt now would only
            # fail and wait before the next one.
            return
        account = await sync_to_async(
            Account.objects.filter(user_id=client.user_id).first
        )()
        if account is None:
            return
        rooms = await sync_to_async(Room.with_speaker_work)(account)
        spaces = await sync_to_async(Space.with_speaker_work)(account)
        for room in [*rooms, *spaces]:
            wanted = await sync_to_async(room.wants_speaker)()
            if wanted == room.speaker_shown:
                continue
            if self._speaker_retry_at.get(room.room_id, 0) > time.monotonic():
                continue
            try:
                if wanted:
                    await self._show_speaker(client, room)
                else:
                    await self._restore_avatar(client, room)
                self._speaker_retry_at.pop(room.room_id, None)
            except Exception:
                logger.exception("Could not update the avatar of %s", room.room_id)
                self._speaker_retry_at[room.room_id] = time.monotonic() + _SPEAKER_RETRY
        for space in await sync_to_async(Space.unused)(account):
            logger.info("Leaving space %s: no chat changes its avatar", space)
            await client.room_leave(space.room_id)
            await sync_to_async(space.delete)()

    @staticmethod
    async def _avatar_state(client, target):
        """Whether the bot may change the avatar of ``target`` - a chat or
        a space - and what it is now, as a
        :py:class:`~matrix_jitsi_bot.space.AvatarState`.

        A chat is looked up in what ``client`` has synced. A space is
        asked of the homeserver: after a restart, ``client`` may not hold
        it as a joined room, though the bot is in it.
        """
        from .db.models import Space
        from .space import AvatarState, SpaceError, read_avatar_state

        if isinstance(target, Space):
            try:
                return await read_avatar_state(client, target.room_id)
            except SpaceError as exc:
                raise RuntimeError(str(exc)) from exc
        matrix_room = client.rooms.get(target.room_id)
        if matrix_room is None:
            return AvatarState(may_change=False, url=None)
        return AvatarState(
            may_change=matrix_room.power_levels.can_user_send_state(
                client.user_id, "m.room.avatar"
            ),
            url=matrix_room.room_avatar_url,
        )

    @staticmethod
    async def _set_room_avatar(
        client, room_id: str, image: bytes | None, content_type: str
    ) -> None:
        """Upload ``image`` and make it the avatar of ``room_id``, or
        remove the avatar if ``image`` is ``None``.
        """
        import io

        import nio

        content = {}
        if image is not None:
            upload, _ = await client.upload(
                io.BytesIO(image),
                content_type=content_type,
                filename="avatar",
                filesize=len(image),
            )
            if isinstance(upload, nio.UploadError):
                raise RuntimeError(f"Upload failed: {upload.message}")
            content = {"url": upload.content_uri}
        response = await client.room_put_state(
            room_id, "m.room.avatar", content, state_key=""
        )
        if isinstance(response, nio.RoomPutStateError):
            raise RuntimeError(f"Setting the avatar failed: {response.message}")  # noqa: TRY004 - a failed response, not a bad type

    async def _show_speaker(self, client, room) -> None:
        """Cache the avatar of ``room`` - a chat or a space - then draw
        the speaker over it.
        """
        import asyncio

        import nio
        from asgiref.sync import sync_to_async

        from .db.models import Space

        avatar = await self._avatar_state(client, room)
        if not avatar.may_change:
            raise RuntimeError("Not allowed to change the room avatar")
        avatar_url = avatar.url
        original, content_type = None, ""
        if avatar_url:
            download = await client.download(mxc=avatar_url)
            if isinstance(download, nio.DownloadError):
                raise RuntimeError(f"Download failed: {download.message}")
            original, content_type = download.body, download.content_type
        merger = self.merger_without_avatar
        if original:
            merger = (
                self.merger_space_with_avatar
                if isinstance(room, Space)
                else self.merger_with_avatar
            )
        image = await asyncio.to_thread(merger.merge, original)
        await sync_to_async(room.cache_avatar)(original, content_type)
        try:
            await self._set_room_avatar(client, room.room_id, image, "image/png")
        except Exception:
            await sync_to_async(room.uncache_avatar)()
            raise
        logger.info("Showing the speaker on the avatar of %s", room.room_id)

    @staticmethod
    async def _restore_avatar(client, room) -> None:
        """Put back the avatar cached for ``room``, and uncache it."""
        from asgiref.sync import sync_to_async

        if not (await MatrixJitsiBot._avatar_state(client, room)).may_change:
            raise RuntimeError("Not allowed to change the room avatar")
        original = bytes(room.original_avatar) if room.original_avatar else None
        await MatrixJitsiBot._set_room_avatar(
            client, room.room_id, original, room.original_avatar_type
        )
        await sync_to_async(room.uncache_avatar)()
        logger.info("Restored the avatar of %s", room.room_id)

    def _start_monitor(self, client, jitsi_room) -> None:
        """Monitor ``jitsi_room`` in a background task, until it ends
        - forgetting itself then, so the next poll checks it normally
        again (which is how a failed monitor is retried).
        """
        import asyncio

        url = jitsi_room.url

        async def _monitor() -> None:
            """Monitor ``jitsi_room``, logging why it ended if it failed."""
            try:
                await jitsi_room.monitor_and_notify(client, self._process)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Lost monitoring of Jitsi conference %s", url)

        logger.info("Staying in Jitsi conference %s to monitor it", url)
        task = asyncio.create_task(_monitor())
        self._monitors[url] = task
        task.add_done_callback(
            lambda done: self._monitors.get(url) is done and self._monitors.pop(url)
        )

    async def _stop_unwanted_monitors(self) -> None:
        """Leave every monitored conference nothing wants monitored
        anymore - untracked, its trackers paused or no longer
        interested in joins and leaves - see
        :py:meth:`~matrix_jitsi_bot.db.models.jitsi.JitsiRoom.wants_participants_check`.
        """
        from asgiref.sync import sync_to_async

        from .db.models import JitsiRoom

        for url, task in list(self._monitors.items()):
            jitsi_room = await sync_to_async(JitsiRoom.objects.filter(url=url).first)()
            wanted = (
                jitsi_room is not None
                and await sync_to_async(jitsi_room.wants_participants_check)()
            )
            if not wanted:
                logger.info("Leaving Jitsi conference %s - no longer monitored", url)
                task.cancel()
                self._monitors.pop(url, None)

    async def _stop_all_monitors(self) -> None:
        """Leave every monitored conference."""
        import asyncio
        import contextlib

        tasks = list(self._monitors.values())
        self._monitors.clear()
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def poll_jitsi_rooms_all(self, client) -> int:
        """Check *every* tracked
        :py:class:`~matrix_jitsi_bot.db.models.jitsi.JitsiRoom` once,
        regardless of whether it's currently due - unlike
        :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.poll_jitsi_rooms_once`,
        which only checks due ones. Used by
        :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.run_once` so a
        single invocation can guarantee everything was actually
        queried - and the avatars match what was found, see
        :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.update_speaker_avatars`.
        Returns how many conferences were checked.
        """
        from asgiref.sync import sync_to_async

        from .db.models import JitsiRoom

        jitsi_rooms = await sync_to_async(JitsiRoom.tracked)()
        await self._check_jitsi_rooms(client, jitsi_rooms)
        await self.update_speaker_avatars(client)
        await self.update_status_messages(client)
        return len(jitsi_rooms)

    @staticmethod
    async def _check_jitsi_rooms(client, jitsi_rooms) -> None:
        """Check each of ``jitsi_rooms`` once, logging (rather than
        propagating) any single one's failure so one bad check doesn't
        stop the rest - shared by
        :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.poll_jitsi_rooms_once`
        and
        :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.poll_jitsi_rooms_all`.
        """
        for jitsi_room in jitsi_rooms:
            try:
                await jitsi_room.check_and_notify(client)
            except Exception:
                logger.exception("Failed to check Jitsi conference %s", jitsi_room.url)

    async def poll_jitsi_rooms_forever(self, client, wait: float) -> None:
        """Check every due
        :py:class:`~matrix_jitsi_bot.db.models.jitsi.JitsiRoom` (see
        :py:meth:`~matrix_jitsi_bot.db.models.jitsi.JitsiRoom.next_check_interval`)
        and notify tracking rooms of anything that changed, forever,
        waking up every ``wait`` seconds to look for one that's due -
        or every
        :py:data:`~matrix_jitsi_bot.bot._IDLE_POLL_INTERVAL` while
        nothing is tracked anywhere (see
        :py:meth:`~matrix_jitsi_bot.db.models.jitsi.JitsiRoom.tracked`),
        since there's nothing that could ever become due in the
        meantime - waking every ``wait`` seconds regardless would just
        burn CPU on an empty query, especially with ``wait``'s default
        of a single second.
        """
        import asyncio

        from asgiref.sync import sync_to_async

        from .db.models import JitsiRoom, Room, Space

        try:
            while True:
                await self.poll_jitsi_rooms_once(client)
                anything_tracked = await sync_to_async(JitsiRoom.is_anything_tracked)()
                anything_tracked = (
                    anything_tracked
                    or await sync_to_async(
                        lambda: (
                            Room.objects.filter(speaker_shown=True).exists()
                            or Space.objects.filter(speaker_shown=True).exists()
                        )
                    )()
                )
                await asyncio.sleep(wait if anything_tracked else _IDLE_POLL_INTERVAL)
        finally:
            await self._stop_all_monitors()


#: How long, in seconds,
#: :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.poll_jitsi_rooms_forever`
#: sleeps between checks while nothing is tracked anywhere at all -
#: much longer than the default ``wait`` (1s) used once something is,
#: since there's nothing that could ever become due in the meantime.
_IDLE_POLL_INTERVAL = 30

#: How long, in seconds, after a failed avatar change the next attempt
#: for that room waits - see
#: :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.update_speaker_avatars`.
_SPEAKER_RETRY = 60

#: How long, in seconds, after a failed edit of a status message the next
#: attempt for it waits - see
#: :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.update_status_messages`.
_STATUS_RETRY = 60

#: Posted into a room the moment it gets a bare, unconfigured `Room`
#: row - whether from a fresh invite (`_register_room_on_invite`) or
#: from finding it already joined but missing from the database at
#: startup (`MatrixJitsiBot.reconcile_joined_rooms`) - so the room
#: isn't left silently un-set-up.
_NEEDS_CONFIGURATION_MESSAGE = (
    'This room isn\'t configured yet. Say "help" to see what a '
    "moderator can set up here."
)


async def _is_space_invite(client: niobot.NioBot, room: nio.MatrixRoom) -> bool:
    """Whether the room ``room`` the bot is invited to is a Matrix space.

    An invitation shows only a few state events of the room, and a
    homeserver may leave out the one that says what kind of room it is
    (its ``m.room.create``) - then ``room.room_type`` is ``None``.
    So the bot joins the room, as it does anyway, and reads that from
    its state. A room it cannot join or read is taken for a chat.
    """
    import nio

    if room.room_type is not None:
        return _is_space(room)
    joined = await client.join(room.room_id)
    if isinstance(joined, nio.JoinError):
        logger.warning("Could not join %s: %s", room.room_id, joined.message)
        return False
    state = await client.room_get_state(room.room_id)
    if isinstance(state, nio.RoomGetStateError):
        logger.warning("Could not read %s: %s", room.room_id, state.message)
        return False
    return any(
        event.get("type") == "m.room.create"
        and event.get("content", {}).get("type") == "m.space"
        for event in state.events
    )


def _is_space(room: nio.MatrixRoom) -> bool:
    """Whether ``room`` is a Matrix space - a room that lists rooms, not
    a chat the bot is configured in.
    """
    return getattr(room, "room_type", None) == "m.space"


def _add_invite_handler(client: niobot.NioBot, account: Account) -> None:
    """Have ``client`` act on invitations to ``account`` - see
    :py:func:`~matrix_jitsi_bot.bot._register_room_on_invite`.
    """
    import nio

    client.add_event_callback(
        lambda room, event: _register_room_on_invite(client, account, room, event),
        nio.InviteMemberEvent,
    )


@_log_errors
async def _register_room_on_invite(
    client: niobot.NioBot,
    account: Account,
    room: nio.MatrixRoom,
    event: nio.InviteMemberEvent,
) -> None:
    """Track invited-into rooms so they have a settings row - unless its
    name opts it out of the bot entirely (see
    :py:func:`~matrix_jitsi_bot.jitsi.opts_out_of_bot`), in which case
    leave right away instead.

    The bot itself already auto-joins invited rooms (niobot's default
    behaviour) - spaces too, which are not set up as chats, see
    :py:func:`~matrix_jitsi_bot.bot._is_space_invite`; this just makes
    sure every other room it's in has a Room row,
    tagged with ``account`` (see
    :py:meth:`~matrix_jitsi_bot.db.models.room.Room.ensure_account`),
    and announces it (see
    :py:data:`~matrix_jitsi_bot.bot._NEEDS_CONFIGURATION_MESSAGE`) if
    that row didn't already exist.
    """
    if event.state_key != account.user_id:
        return

    from .jitsi import opts_out_of_bot

    room_name = getattr(room, "name", None) or ""
    if opts_out_of_bot(room_name):
        logger.info("Leaving room %s: name opts out of the bot", room.room_id)
        await client.room_leave(room.room_id)
        return
    if await _is_space_invite(client, room):
        logger.info("Accepted the invite to space %s", room.room_id)
        return

    from asgiref.sync import sync_to_async

    from .db.models import Room

    created_room, created = await sync_to_async(Room.objects.get_or_create)(
        room_id=room.room_id
    )
    await sync_to_async(created_room.ensure_account)(account)
    await sync_to_async(created_room.update_name)(room_name)
    if created:
        logger.info("Joined room %s", room.room_id)
        await client.send_message(room.room_id, _NEEDS_CONFIGURATION_MESSAGE)


@_log_errors
async def _sync_room_members(
    account: Account, room: nio.MatrixRoom, event: nio.RoomMemberEvent
) -> None:
    """Keep
    :py:class:`~matrix_jitsi_bot.db.models.room.RoomMember` in sync
    with nio's view of who is in the room - see
    :py:meth:`~matrix_jitsi_bot.db.models.room.Room.sync_members_of`.

    This is registered for ``nio.RoomMemberEvent``, which - contrary to
    what its name suggests - only ever fires for a room the client is
    still (or newly) *joined* to: the installed ``nio``'s own
    ``AsyncClient._handle_sync`` calls ``_handle_joined_rooms`` and
    ``_handle_invited_rooms``, but nothing for a sync's ``rooms.leave``
    section, so this callback silently never runs for the bot's own
    removal from a room. See
    :py:func:`~matrix_jitsi_bot.bot._forget_left_rooms` (from the raw
    sync response instead) and
    :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.reconcile_joined_rooms`
    (at startup) for where that's actually handled.

    Also keeps
    :py:attr:`~matrix_jitsi_bot.db.models.account.Account.display_name`
    live: an ``m.room.member`` event whose ``state_key`` is this very
    account is its own membership state - joins, and any later profile
    change, both included - propagated to every room it shares. See
    :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot._sync_own_display_name`
    for the startup equivalent.
    """
    from asgiref.sync import sync_to_async

    from .db.models import Room

    if _is_space(room):
        return
    await sync_to_async(Room.sync_members_of)(
        room.room_id,
        dict(room.users),
        dict(room.invited_users),
        room.power_levels.get_user_level,
        account=account,
    )
    await sync_to_async(Room.update_name_of)(room.room_id, room.name)
    if event.state_key == account.user_id:
        await sync_to_async(account.update_display_name)(
            event.content.get("displayname")
        )


@_log_errors
async def _refresh_own_avatar(
    client: niobot.NioBot, account: Account, event: nio.RoomMemberEvent
) -> None:
    """When a membership event of this very account shows that its
    profile avatar is not the one stored, store the new one - see
    :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.sync_own_avatar`. An
    ``m.room.member`` event of the account is its profile in that room,
    so a change of the avatar shows in every room it shares.
    """
    from asgiref.sync import sync_to_async

    if event.state_key != account.user_id:
        return
    await sync_to_async(account.refresh_from_db)()
    if (event.content.get("avatar_url") or "") != account.avatar_mxc:
        await MatrixJitsiBot.sync_own_avatar(client, account)


@_log_errors
async def _forget_deleted_status_message(
    _room: nio.MatrixRoom, event: nio.RedactionEvent
) -> None:
    """Stop editing a status message that somebody deleted - that is how
    a chat stops it.
    """
    from asgiref.sync import sync_to_async

    from .db.models import StatusMessage

    deleted, _ = await sync_to_async(
        StatusMessage.objects.filter(event_id=event.redacts).delete
    )()
    if deleted:
        logger.info("The status message %s was deleted", event.redacts)


async def _sync_room_name(room: nio.MatrixRoom, event: nio.RoomNameEvent) -> None:
    """Keep
    :py:attr:`~matrix_jitsi_bot.db.models.room.Room.name` in sync with
    an explicit rename - a ``nio.RoomMemberEvent`` (see
    :py:func:`~matrix_jitsi_bot.bot._sync_room_members`) only refreshes
    it as a side effect of a membership change, which a bare rename
    isn't.
    """
    from asgiref.sync import sync_to_async

    from .db.models import Room

    await sync_to_async(Room.update_name_of)(room.room_id, room.name)


@_log_errors
async def _forget_left_rooms(response: nio.SyncResponse) -> None:
    """Forget (see
    :py:meth:`~matrix_jitsi_bot.db.models.room.Room.forget`) any room
    whose ID appears in this sync's ``rooms.leave`` - the bot was
    removed from it (kicked, banned, or left some other way not
    through its own ``leave`` command) since the last sync, while this
    process was running. See
    :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.reconcile_joined_rooms`
    for the equivalent check at startup, which also catches a removal
    that happened while the bot *wasn't* running - something a sync
    response, covering only what changed since the last one, can't.

    A space is not forgotten: it is no chat with settings of its own,
    but what the chats that list it asked for - and a bot that leaves
    and rejoins it, e.g. while somebody tests, must not lose that. A
    space the bot does not use anymore is left, and forgotten, by
    :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.update_speaker_avatars`.

    Read directly from ``response.rooms.leave`` rather than via a
    ``nio.RoomMemberEvent`` callback - see
    :py:func:`~matrix_jitsi_bot.bot._sync_room_members` for why that
    doesn't work.
    """
    from asgiref.sync import sync_to_async

    from .db.models import Room

    for room_id in response.rooms.leave:
        logger.info("No longer in room %s - forgetting it", room_id)
        await sync_to_async(Room.forget)(room_id)
