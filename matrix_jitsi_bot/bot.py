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
from .matrix_login import LoginCheckResult, check_login, homeserver_from_user_id

if TYPE_CHECKING:
    import asyncio
    from datetime import datetime
    from pathlib import Path

    import nio
    import niobot

    from .db.models import Account
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


@dataclass
class RoomStatus:
    """A DB-only snapshot of one room the bot is in - see
    :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.status_report`.
    """

    room_id: str
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
        await self._run_client(account, wait)

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
        import asyncio
        import contextlib

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

    def _build_client(self, account: Account) -> tuple[niobot.NioBot, asyncio.Event]:
        """Construct a niobot client wired up with every event callback
        the bot needs (invites, member sync, messages) and a one-shot
        room reconciliation on its first sync (see
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
        )
        client.add_event_callback(
            lambda room, event: _register_room_on_invite(client, account, room, event),
            nio.InviteMemberEvent,
        )
        client.add_event_callback(
            lambda room, event: _sync_room_members(account, room, event),
            nio.RoomMemberEvent,
        )
        client.add_event_callback(
            lambda room, event: self.interaction.on_matrix_message(client, room, event),
            nio.RoomMessageText,
        )

        reconciled = asyncio.Event()

        async def _reconcile_once(_response: nio.SyncResponse) -> None:
            """Run ``reconcile_joined_rooms`` once, on the first sync
            response only - see its own docstring for why.
            """
            if reconciled.is_set():
                return
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
            room, created = await sync_to_async(Room.objects.get_or_create)(
                room_id=room_id
            )
            await sync_to_async(room.ensure_account)(account)
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
        left it. A ``staticmethod``: called from
        :py:meth:`~matrix_jitsi_bot.interactions.base.BotInteraction.on_matrix_message`,
        which has no
        :py:class:`~matrix_jitsi_bot.bot.MatrixJitsiBot` instance of
        its own to call this on.
        """
        from asgiref.sync import sync_to_async

        from .db.models import Room

        if not await sync_to_async(Room.is_flagged_to_leave)(room_id):
            return
        logger.info("Leaving room %s", room_id)
        await client.room_leave(room_id)
        await sync_to_async(Room.forget)(room_id)

    async def poll_jitsi_rooms_once(self, client) -> None:
        """Check every currently-due
        :py:class:`~matrix_jitsi_bot.db.models.jitsi.JitsiRoom` once -
        see
        :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot._check_jitsi_rooms`.
        """
        from asgiref.sync import sync_to_async

        from .db.models import JitsiRoom

        await self._check_jitsi_rooms(client, await sync_to_async(JitsiRoom.due)())

    async def poll_jitsi_rooms_all(self, client) -> int:
        """Check *every* tracked
        :py:class:`~matrix_jitsi_bot.db.models.jitsi.JitsiRoom` once,
        regardless of whether it's currently due - unlike
        :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.poll_jitsi_rooms_once`,
        which only checks due ones. Used by
        :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.run_once` so a
        single invocation can guarantee everything was actually
        queried. Returns how many conferences were checked.
        """
        from asgiref.sync import sync_to_async

        from .db.models import JitsiRoom

        jitsi_rooms = await sync_to_async(JitsiRoom.tracked)()
        await self._check_jitsi_rooms(client, jitsi_rooms)
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

        from .db.models import JitsiRoom

        while True:
            await self.poll_jitsi_rooms_once(client)
            anything_tracked = await sync_to_async(JitsiRoom.is_anything_tracked)()
            await asyncio.sleep(wait if anything_tracked else _IDLE_POLL_INTERVAL)


#: How long, in seconds,
#: :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.poll_jitsi_rooms_forever`
#: sleeps between checks while nothing is tracked anywhere at all -
#: much longer than the default ``wait`` (1s) used once something is,
#: since there's nothing that could ever become due in the meantime.
_IDLE_POLL_INTERVAL = 30

#: Posted into a room the moment it gets a bare, unconfigured `Room`
#: row - whether from a fresh invite (`_register_room_on_invite`) or
#: from finding it already joined but missing from the database at
#: startup (`MatrixJitsiBot.reconcile_joined_rooms`) - so the room
#: isn't left silently un-set-up.
_NEEDS_CONFIGURATION_MESSAGE = (
    'This room isn\'t configured yet. Say "help" to see what a '
    "moderator can set up here."
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
    behaviour); this just makes sure every room it's in has a Room row,
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

    from asgiref.sync import sync_to_async

    from .db.models import Room

    created_room, created = await sync_to_async(Room.objects.get_or_create)(
        room_id=room.room_id
    )
    await sync_to_async(created_room.ensure_account)(account)
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
    """
    from asgiref.sync import sync_to_async

    from .db.models import Room

    await sync_to_async(Room.sync_members_of)(
        room.room_id,
        dict(room.users),
        dict(room.invited_users),
        room.power_levels.get_user_level,
        account=account,
    )


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
