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
