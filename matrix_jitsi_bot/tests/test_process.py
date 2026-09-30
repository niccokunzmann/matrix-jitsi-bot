"""The bot process record, the conference monitors, and their ``status``."""

from __future__ import annotations

import asyncio
import contextlib
import os
import subprocess
import sys
from unittest.mock import AsyncMock

import pytest
from asgiref.sync import sync_to_async
from typer.testing import CliRunner

from matrix_jitsi_bot.bot import MatrixJitsiBot, _acquire_locks
from matrix_jitsi_bot.cli import app
from matrix_jitsi_bot.db.models import (
    Account,
    AlreadyRunning,
    BotProcess,
    JitsiMonitor,
    JitsiRoom,
    LockUnavailable,
    Room,
    RunLock,
    TrackedJitsiRoom,
)
from matrix_jitsi_bot.db.models.process import account_lock_path, lock_path
from matrix_jitsi_bot.jitsi import JitsiStatus

runner = CliRunner()


LOCK_HOLDER = """
import fcntl, sys, time
file = open(sys.argv[1], "a")
fcntl.flock(file, fcntl.LOCK_EX)
print("locked", flush=True)
time.sleep(60)
"""


@contextlib.contextmanager
def _other_process_holding_the_lock():
    """Another process that runs, holding the run lock - like another bot."""
    process = subprocess.Popen(  # noqa: S603
        [sys.executable, "-c", LOCK_HOLDER, str(lock_path())],
        stdout=subprocess.PIPE,
    )
    process.stdout.readline()  # it has the lock now
    try:
        yield process
    finally:
        process.kill()
        process.wait()


def test_register_records_this_process() -> None:
    process = BotProcess.register()

    assert process.pid == os.getpid()
    assert len(process.secret) == 32


def test_recorded_processes_only_count_while_the_lock_is_held() -> None:
    process = BotProcess.register()
    assert BotProcess.alive() == []

    lock = RunLock()
    lock.acquire()
    try:
        assert BotProcess.alive() == [process]
    finally:
        lock.release()
    assert BotProcess.alive() == []


def test_the_lock_is_exclusive_and_released_by_the_kernel_when_a_process_dies() -> None:
    with _other_process_holding_the_lock() as other:
        assert RunLock.is_held()
        with pytest.raises(AlreadyRunning):
            RunLock().acquire()
        # Killed, not shut down: nothing had the chance to clean up.
        other.kill()
        other.wait()
        assert not RunLock.is_held()
        lock = RunLock()
        lock.acquire()
        lock.release()


def test_two_locks_in_one_process_exclude_each_other() -> None:
    first = RunLock()
    first.acquire()
    try:
        with pytest.raises(AlreadyRunning):
            RunLock().acquire()
    finally:
        first.release()
    assert not RunLock.is_held()


def test_a_killed_bot_leaves_nothing_that_stops_a_new_one(monkeypatch) -> None:
    """Whatever an interrupted process left in the database - even with
    a process ID that is alive again, like 1 in a container - is cleared
    out when the next bot starts.
    """
    jitsi_room = JitsiRoom.objects.create(url="https://meet.example.org/Room")
    stale = BotProcess.objects.create(pid=1, secret="x")
    JitsiMonitor.begin(jitsi_room, stale)
    seen = []

    _run_with_fake_client(monkeypatch, seen)

    (running,) = seen
    assert [p.pid for p in running] == [os.getpid()]
    assert not JitsiMonitor.objects.exists()


def test_a_monitor_exists_while_the_bot_is_in_the_conference(monkeypatch) -> None:
    jitsi_room = JitsiRoom.objects.create(url="https://meet.example.org/Room")
    room = Room.objects.create(room_id="!room:example.org")
    TrackedJitsiRoom.objects.create(room=room, jitsi_room=jitsi_room, track_joins=True)
    process = BotProcess.register()
    seen = []

    async def _monitor(url, *, name=None):
        seen.append(await sync_to_async(list)(JitsiMonitor.objects.all()))
        yield JitsiStatus(is_open=True, participants=["Alice"], attempts=2)
        seen.append(await sync_to_async(list)(JitsiMonitor.objects.all()))
        yield JitsiStatus(is_open=False, participants=[])

    monkeypatch.setattr("matrix_jitsi_bot.jitsi.monitor_jitsi_room", _monitor)

    asyncio.run(jitsi_room.monitor_and_notify(AsyncMock(), process))

    (before_first,), (during,) = seen
    assert before_first.process == process
    assert during.attempts == 2
    assert during.last_state_at is not None
    # Left again: nothing is left of it.
    assert not JitsiMonitor.objects.exists()


def test_the_monitor_is_deleted_when_the_bot_is_told_to_leave(monkeypatch) -> None:
    jitsi_room = JitsiRoom.objects.create(url="https://meet.example.org/Room")

    async def _forever(url, *, name=None):
        await asyncio.Event().wait()
        yield

    monkeypatch.setattr("matrix_jitsi_bot.jitsi.monitor_jitsi_room", _forever)

    async def _scenario():
        task = asyncio.create_task(jitsi_room.monitor_and_notify(AsyncMock()))
        while not await sync_to_async(JitsiMonitor.objects.exists)():  # noqa: ASYNC110
            await asyncio.sleep(0.01)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(_scenario())

    assert not JitsiMonitor.objects.exists()


def _run_with_fake_client(monkeypatch, seen):
    Account.objects.create(user_id="@bot:example.org", homeserver="https://example.org")

    async def _fake_run_client(self, account, wait):
        seen.append(await sync_to_async(list)(BotProcess.objects.all()))

    monkeypatch.setattr(MatrixJitsiBot, "_run_client", _fake_run_client)
    asyncio.run(MatrixJitsiBot().run("@bot:example.org"))


def test_run_registers_itself_and_removes_itself_when_it_stops(monkeypatch) -> None:
    seen = []
    held = []

    async def _fake_run_client(self, account, wait):
        seen.append(await sync_to_async(list)(BotProcess.objects.all()))
        held.append(RunLock.is_held())

    Account.objects.create(user_id="@bot:example.org", homeserver="https://example.org")
    monkeypatch.setattr(MatrixJitsiBot, "_run_client", _fake_run_client)
    asyncio.run(MatrixJitsiBot().run("@bot:example.org"))

    assert [[p.pid for p in seen[0]], held] == [[os.getpid()], [True]]
    assert not BotProcess.objects.exists()
    assert not RunLock.is_held()


def test_run_refuses_to_run_next_to_a_running_process(monkeypatch) -> None:
    Account.objects.create(user_id="@bot:example.org", homeserver="https://example.org")

    async def _never(self, account, wait):
        raise AssertionError("must not run")

    monkeypatch.setattr(MatrixJitsiBot, "_run_client", _never)
    with _other_process_holding_the_lock(), pytest.raises(AlreadyRunning):
        asyncio.run(MatrixJitsiBot().run("@bot:example.org"))


def test_run_once_refuses_while_a_process_is_running() -> None:
    Account.objects.create(user_id="@bot:example.org", homeserver="https://example.org")
    with _other_process_holding_the_lock():
        result = runner.invoke(app, ["run", "--once"])

    assert result.exit_code == 1
    assert "already running" in result.output


def test_run_once_does_not_start_next_to_run(monkeypatch) -> None:
    """The other way around: ``run`` holds the lock, so ``run --once`` can't run."""
    Account.objects.create(user_id="@bot:example.org", homeserver="https://example.org")
    lock = RunLock()
    lock.acquire()
    try:
        result = runner.invoke(app, ["run", "--once"])
    finally:
        lock.release()
    assert result.exit_code == 1


def test_run_once_lets_the_next_run_start(monkeypatch) -> None:
    Account.objects.create(user_id="@bot:example.org", homeserver="https://example.org")

    def _reached(self, account):
        raise RuntimeError("got past the lock")

    monkeypatch.setattr(MatrixJitsiBot, "_build_client", _reached)
    with pytest.raises(RuntimeError, match="got past the lock"):
        asyncio.run(MatrixJitsiBot().run_once())
    assert not RunLock.is_held()


def test_status_shows_no_process_and_no_monitored_conference() -> None:
    result = runner.invoke(app, ["status"])

    assert "Processes running: 0" in result.output
    assert "Monitored conferences: none" in result.output


def test_status_shows_the_running_process_and_monitored_conferences() -> None:
    jitsi_room = JitsiRoom.objects.create(
        url="https://meet.example.org/Room", is_open=True, participants=["Alice", "Bob"]
    )
    process = BotProcess.register()
    JitsiMonitor.begin(jitsi_room, process)
    lock = RunLock()
    lock.acquire()

    try:
        result = runner.invoke(app, ["status"])
    finally:
        lock.release()

    assert "Processes running: 1" in result.output
    assert f"process {process.pid}" in result.output
    assert "Monitored conferences:" in result.output
    assert "https://meet.example.org/Room" in result.output
    assert "with Alice, Bob" in result.output


def test_status_ignores_what_an_interrupted_process_left_behind() -> None:
    jitsi_room = JitsiRoom.objects.create(url="https://meet.example.org/Room")
    JitsiMonitor.begin(jitsi_room, BotProcess.objects.create(pid=123, secret="x"))

    result = runner.invoke(app, ["status"])

    assert "Processes running: 0" in result.output
    assert "Monitored conferences: none" in result.output


BOT_PROCESS = """
from matrix_jitsi_bot.bot import MatrixJitsiBot
bot = MatrixJitsiBot()
from matrix_jitsi_bot.db.models import Account
import time
account = Account(user_id="@kill:example.org", homeserver="https://example.org")
bot._register_process(account)
print("running", flush=True)
time.sleep(60)
"""


def test_a_bot_killed_with_sigkill_can_be_replaced(tmp_path) -> None:
    """A real bot process registering as the running one, then killed
    without any chance to clean up: the next one starts, and takes over.
    """
    env = {**os.environ, "MJB_DB": str(tmp_path / "test.sqlite3")}
    bot = subprocess.Popen(  # noqa: S603
        [sys.executable, "-c", BOT_PROCESS], env=env, stdout=subprocess.PIPE
    )
    try:
        assert bot.stdout.readline().strip() == b"running"
        assert [p.pid for p in BotProcess.alive()] == [bot.pid]
        with pytest.raises(AlreadyRunning):
            MatrixJitsiBot()._register_process(_account("@kill:example.org"))
        # Another database, same account: refused too.
        with pytest.raises(AlreadyRunning, match="another database"):
            RunLock(
                account_lock_path("@kill:example.org"), message="another database"
            ).acquire()

        bot.kill()
        bot.wait()

        assert BotProcess.alive() == []
        replacement = MatrixJitsiBot()
        replacement._register_process(_account("@kill:example.org"))
        assert [p.pid for p in BotProcess.alive()] == [os.getpid()]
        replacement._lock.release()
    finally:
        bot.kill()
        bot.wait()


def _account(user_id: str) -> Account:
    return Account(user_id=user_id, homeserver="https://example.org")


def test_the_same_account_cannot_run_for_two_databases() -> None:
    """Another database's bot holds the account's lock, but not this
    database's own.
    """
    other_database = RunLock(account_lock_path("@shared:example.org"))
    other_database.acquire()
    try:
        with pytest.raises(AlreadyRunning, match="another database"):
            _acquire_locks(_account("@shared:example.org"))
        # The refused start didn't keep this database's own lock.
        assert not RunLock.is_held()
    finally:
        other_database.release()


def test_a_file_system_that_cannot_lock_is_reported(monkeypatch) -> None:
    import errno
    import fcntl

    def _no_locks(file, operation):
        raise OSError(errno.ENOLCK, "No locks available")

    monkeypatch.setattr(fcntl, "flock", _no_locks)

    with pytest.raises(LockUnavailable, match="local file system"):
        RunLock().acquire()


def test_a_manual_check_does_not_join_a_conference_the_bot_is_in(
    send_message, monkeypatch
) -> None:
    jitsi_room = JitsiRoom.objects.create(
        url="https://meet.example.org/Room", is_open=True, participants=["Alice"]
    )
    conversation = send_message("@bot: check https://meet.example.org/Room")
    TrackedJitsiRoom.objects.create(
        room=conversation.room, jitsi_room=jitsi_room, track_joins=True
    )
    process = BotProcess.register()
    JitsiMonitor.begin(jitsi_room, process)
    lock = RunLock()
    lock.acquire()

    async def _no_joining(url, *, want_participants=True, name=None):
        raise AssertionError("joined a conference the bot is already in")

    monkeypatch.setattr("matrix_jitsi_bot.jitsi.check_jitsi_room", _no_joining)
    try:
        assert JitsiMonitor.is_active(jitsi_room)
        from matrix_jitsi_bot.db.models import JitsiInteraction

        reply = JitsiInteraction().react_to_matrix_message(conversation)
    finally:
        lock.release()

    assert reply.text == "https://meet.example.org/Room: open, with Alice"
