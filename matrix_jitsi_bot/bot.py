"""Programmatic interface to the Matrix Jitsi Bot.

`cli.py` is a thin command-line wrapper around `MatrixJitsiBot` - anything
it can do can also be done directly from Python.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import django as mjb_django
from .matrix_login import LoginCheckResult, check_login, homeserver_from_user_id

if TYPE_CHECKING:
    from pathlib import Path

    from .db.models import Account
    from .interactions import BotInteraction


class MatrixJitsiBot:
    """Manage Matrix accounts, the database, and run the bot.

    Registered `BotInteraction`s react to messages in rooms the bot has
    joined - plug them in via `interactions=` or `add_interaction()`.
    """

    def __init__(self, interactions: list[BotInteraction] | None = None) -> None:
        mjb_django.setup_django()
        self.interactions: list[BotInteraction] = list(interactions or [])

    def add_interaction(self, interaction: BotInteraction) -> None:
        """Register a `BotInteraction` the running bot should react through."""
        self.interactions.append(interaction)

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

        `homeserver` defaults to a guess from `user_id`'s server name -
        see `homeserver_from_user_id` - pass it explicitly if that
        homeserver delegates its client-server API elsewhere.

        Unless `test` is `False`, the credentials are first verified
        against the homeserver; `LoginFailed` propagates if that fails
        and nothing is saved.

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
        from .db.models import Account

        return list(Account.objects.order_by("user_id"))

    def get_account(self, user_id: str) -> Account:
        """Look up an account. Raises `Account.DoesNotExist` if there is none."""
        from .db.models import Account

        return Account.objects.get(user_id=user_id)

    def remove_account(self, user_id: str) -> bool:
        """Remove an account. Returns whether one was actually removed."""
        from .db.models import Account

        deleted, _ = Account.objects.filter(user_id=user_id).delete()
        return bool(deleted)

    def set_account_password(self, user_id: str, password: str) -> Account:
        account = self.get_account(user_id)
        account.password = password
        account.save(update_fields=["password"])
        return account

    def set_account_access_token(self, user_id: str, access_token: str) -> Account:
        account = self.get_account(user_id)
        account.access_token = access_token
        account.save(update_fields=["access_token"])
        return account

    def set_account_homeserver(self, user_id: str, homeserver: str) -> Account:
        account = self.get_account(user_id)
        account.homeserver = homeserver
        account.save(update_fields=["homeserver"])
        return account

    def set_account_device_id(self, user_id: str, device_id: str) -> Account:
        account = self.get_account(user_id)
        account.device_id = device_id
        account.save(update_fields=["device_id"])
        return account

    async def check_account(self, user_id: str) -> LoginCheckResult:
        """Verify a saved account can still log in. Raises `LoginFailed` if not."""
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
        mjb_django.migrate()

    def makemigrations(self) -> None:
        mjb_django.makemigrations()

    def db_path(self) -> Path:
        return mjb_django.db_path()

    def backup(self, file: Path) -> Path:
        return mjb_django.backup(file)

    def restore(self, file: Path) -> Path:
        return mjb_django.restore(file)

    # -- running -------------------------------------------------------------

    async def run(self, user_id: str | None = None) -> None:
        """Log in and run the bot's main loop until interrupted.

        Uses the only configured account if `user_id` is omitted; raises
        `ValueError` if that's ambiguous (zero or multiple accounts).
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

        await self._run_client(account)

    async def _run_client(self, account: Account) -> None:
        import nio
        import niobot

        client = niobot.NioBot(
            homeserver=account.homeserver,
            user_id=account.user_id,
            device_id=account.device_id or "matrix-jitsi-bot",
            command_prefix="!",
        )
        client.add_event_callback(
            lambda room, event: _register_room_on_invite(client.user_id, room, event),
            nio.InviteMemberEvent,
        )
        client.add_event_callback(_sync_room_members, nio.RoomMemberEvent)
        client.add_event_callback(
            lambda room, event: _react_to_message(
                self.interactions, client, room, event
            ),
            nio.RoomMessageText,
        )

        if account.access_token:
            await client.start(access_token=account.access_token)
        else:
            await client.start(password=account.password)


async def _register_room_on_invite(bot_user_id: str, room, event) -> None:
    """Track invited-into rooms so they have a settings row.

    The bot itself already auto-joins invited rooms (niobot's default
    behaviour); this just makes sure every room it's in has a Room row.
    """
    if event.state_key != bot_user_id:
        return
    from asgiref.sync import sync_to_async

    from .db.models import Room

    await sync_to_async(Room.objects.get_or_create)(room_id=room.room_id)


def _sync_members(
    room_id: str, users: dict, invited_users: dict, get_power_level
) -> None:
    from .db.models import Room, RoomMember

    room, _ = Room.objects.get_or_create(room_id=room_id)
    seen = set()
    for user_id in users:
        RoomMember.objects.update_or_create(
            room=room,
            user_id=user_id,
            defaults={"membership": "join", "power_level": get_power_level(user_id)},
        )
        seen.add(user_id)
    for user_id in invited_users:
        RoomMember.objects.update_or_create(
            room=room,
            user_id=user_id,
            defaults={"membership": "invite", "power_level": get_power_level(user_id)},
        )
        seen.add(user_id)
    room.members.exclude(user_id__in=seen).update(membership="leave")


async def _sync_room_members(room, event) -> None:
    """Keep `RoomMember` in sync with nio's view of who is in the room."""
    from asgiref.sync import sync_to_async

    await sync_to_async(_sync_members)(
        room.room_id,
        dict(room.users),
        dict(room.invited_users),
        room.power_levels.get_user_level,
    )


def _record_message(room_id: str, event):
    from datetime import UTC, datetime

    from .db.models import Conversation, Message, Room

    room, _ = Room.objects.get_or_create(room_id=room_id)
    conversation, _ = Conversation.objects.get_or_create(room=room)
    Message.objects.create(
        conversation=conversation,
        sender=event.sender,
        event_id=event.event_id,
        body=event.body,
        server_timestamp=datetime.fromtimestamp(event.server_timestamp / 1000, tz=UTC),
        source=event.source,
    )
    return conversation


async def _react_to_message(
    interactions: list[BotInteraction], client, room, event
) -> None:
    """Record an incoming message and run registered `BotInteraction`s over it."""
    if event.sender == client.user_id or client.is_old(event):
        return

    from asgiref.sync import sync_to_async

    from .db.models import CommandReply

    conversation = await sync_to_async(_record_message)(room.room_id, event)

    for interaction in interactions:
        result = await sync_to_async(interaction.react_to_matrix_message)(conversation)
        if result is None:
            continue
        if isinstance(result, CommandReply):
            await result.send_message(client)
        else:
            await client.send_message(room, result, reply_to=event)
        return
