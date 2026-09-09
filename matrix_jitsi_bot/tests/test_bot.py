import asyncio

import pytest

from matrix_jitsi_bot.bot import MatrixJitsiBot
from matrix_jitsi_bot.matrix_login import LoginFailed


def test_create_and_list_accounts_without_test() -> None:
    bot = MatrixJitsiBot()

    account, created = asyncio.run(
        bot.create_account(
            "@bot:example.org",
            homeserver="https://example.org",
            password="secret",
            test=False,
        )
    )
    assert created is True
    assert account.homeserver == "https://example.org"

    accounts = bot.list_accounts()
    assert [a.user_id for a in accounts] == ["@bot:example.org"]


def test_create_account_defaults_homeserver_from_user_id() -> None:
    bot = MatrixJitsiBot()

    account, _ = asyncio.run(
        bot.create_account("@bot:example.org", password="secret", test=False)
    )

    assert account.homeserver == "https://example.org"


def test_create_account_test_failure_does_not_save(monkeypatch) -> None:
    bot = MatrixJitsiBot()

    async def _fail(**_kwargs):
        raise LoginFailed("401: bad credentials")

    monkeypatch.setattr("matrix_jitsi_bot.bot.check_login", _fail)

    with pytest.raises(LoginFailed):
        asyncio.run(
            bot.create_account(
                "@bot:example.org",
                homeserver="https://example.org",
                password="wrong",
                test=True,
            )
        )

    assert bot.list_accounts() == []


def test_set_account_password_updates_in_place() -> None:
    from matrix_jitsi_bot.db.models import Account

    Account.objects.create(user_id="@bot:example.org", homeserver="https://example.org")

    bot = MatrixJitsiBot()
    bot.set_account_password("@bot:example.org", "newsecret")

    assert Account.objects.get(user_id="@bot:example.org").password == "newsecret"


def test_get_account_missing_raises() -> None:
    from matrix_jitsi_bot.db.models import Account

    bot = MatrixJitsiBot()
    with pytest.raises(Account.DoesNotExist):
        bot.get_account("@nobody:example.org")


def test_sync_members_creates_and_marks_leave() -> None:
    from matrix_jitsi_bot.bot import _sync_members
    from matrix_jitsi_bot.db.models import Room, RoomMember

    _sync_members("!room:example.org", {"@a:example.org": None}, {}, lambda _uid: 50)

    room = Room.objects.get(room_id="!room:example.org")
    member = RoomMember.objects.get(room=room, user_id="@a:example.org")
    assert member.membership == "join"
    assert member.power_level == 50

    _sync_members("!room:example.org", {}, {}, lambda _uid: 0)
    member.refresh_from_db()
    assert member.membership == "leave"


def test_sync_members_tracks_invited_users() -> None:
    from matrix_jitsi_bot.bot import _sync_members
    from matrix_jitsi_bot.db.models import Room, RoomMember

    _sync_members(
        "!room:example.org", {}, {"@invitee:example.org": None}, lambda _uid: 0
    )

    room = Room.objects.get(room_id="!room:example.org")
    member = RoomMember.objects.get(room=room, user_id="@invitee:example.org")
    assert member.membership == "invite"


def test_react_to_message_survives_a_failing_interaction() -> None:
    from unittest.mock import AsyncMock, MagicMock

    from matrix_jitsi_bot.bot import _react_to_message
    from matrix_jitsi_bot.interactions import BotInteraction

    class Boom(BotInteraction):
        def react_to_matrix_message(self, conversation):
            raise RuntimeError("boom")

    class Greeter(BotInteraction):
        def react_to_matrix_message(self, conversation):
            return "hello"

    room = MagicMock(room_id="!room:example.org")
    event = MagicMock(
        sender="@a:example.org",
        body="hello",
        event_id="$evt1",
        server_timestamp=0,
        source={},
    )
    client = MagicMock(user_id="@bot:example.org")
    client.is_old.return_value = False
    client.send_message = AsyncMock()

    asyncio.run(_react_to_message([Boom(), Greeter()], client, room, event))

    client.send_message.assert_awaited_once_with(room, "hello", reply_to=event)


def test_react_to_message_does_not_propagate_a_recording_failure(monkeypatch) -> None:
    from unittest.mock import MagicMock

    from matrix_jitsi_bot.bot import _react_to_message

    def _fail(*_args, **_kwargs):
        raise RuntimeError("db is on fire")

    monkeypatch.setattr("matrix_jitsi_bot.bot._record_message", _fail)

    room = MagicMock(room_id="!room:example.org")
    event = MagicMock(sender="@a:example.org", body="hello")
    client = MagicMock(user_id="@bot:example.org")
    client.is_old.return_value = False

    asyncio.run(_react_to_message([], client, room, event))
