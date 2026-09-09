from typer.testing import CliRunner

from matrix_jitsi_bot.cli import app

runner = CliRunner()


def _create(user_id: str = "@bot:example.org", password: str = "secret"):
    """Create an account via the CLI, the setup most tests below start from."""
    return runner.invoke(
        app,
        [
            "account",
            "create",
            user_id,
            "--homeserver",
            "https://example.org",
            "--password",
            password,
            "--no-test",
        ],
    )


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip()


def test_account_create_list_show_remove() -> None:
    result = _create()
    assert result.exit_code == 0, result.output
    assert "Created account @bot:example.org" in result.output

    result = runner.invoke(app, ["account", "list"])
    assert result.exit_code == 0, result.output
    assert "@bot:example.org" in result.output
    assert "https://example.org" in result.output

    result = runner.invoke(app, ["account", "show", "@bot:example.org"])
    assert result.exit_code == 0, result.output
    assert "has_password: True" in result.output
    assert "has_token:    False" in result.output
    assert "secret" not in result.output

    result = runner.invoke(app, ["account", "remove", "@bot:example.org"])
    assert result.exit_code == 0, result.output

    result = runner.invoke(app, ["account", "list"])
    assert "No accounts configured." in result.output


def test_account_create_twice_updates_instead_of_erroring() -> None:
    """Creating an already-configured account again updates it rather
    than failing - `user_id` is the unique key either way."""
    result = _create(password="first-password")
    assert result.exit_code == 0, result.output
    assert "Created account @bot:example.org" in result.output

    result = _create(password="second-password")
    assert result.exit_code == 0, result.output
    assert "Updated account @bot:example.org" in result.output

    result = runner.invoke(app, ["account", "list"])
    assert result.output.count("@bot:example.org") == 1


def test_account_show_unknown_account_fails() -> None:
    result = runner.invoke(app, ["account", "show", "@nobody:example.org"])
    assert result.exit_code == 1
    assert "No such account" in result.output


def test_account_set_password() -> None:
    _create()

    result = runner.invoke(
        app,
        ["account", "set", "password", "@bot:example.org", "--password", "newsecret"],
    )
    assert result.exit_code == 0, result.output
    assert "Updated password" in result.output

    from matrix_jitsi_bot.db.models import Account

    account = Account.objects.get(user_id="@bot:example.org")
    assert account.password == "newsecret"


def test_account_set_homeserver() -> None:
    _create()

    result = runner.invoke(
        app,
        ["account", "set", "homeserver", "@bot:example.org", "https://new.example.org"],
    )
    assert result.exit_code == 0, result.output

    from matrix_jitsi_bot.db.models import Account

    account = Account.objects.get(user_id="@bot:example.org")
    assert account.homeserver == "https://new.example.org"


def test_db_backup_and_restore(tmp_path) -> None:
    _create()

    backup_file = tmp_path / "backup.sqlite3"
    result = runner.invoke(app, ["db", "backup", str(backup_file)])
    assert result.exit_code == 0, result.output
    assert backup_file.exists()

    result = runner.invoke(app, ["account", "remove", "@bot:example.org"])
    assert result.exit_code == 0, result.output

    result = runner.invoke(app, ["db", "restore", str(backup_file)])
    assert result.exit_code == 0, result.output

    result = runner.invoke(app, ["account", "list"])
    assert "@bot:example.org" in result.output


def test_db_restore_missing_file_fails(tmp_path) -> None:
    result = runner.invoke(app, ["db", "restore", str(tmp_path / "missing.sqlite3")])
    assert result.exit_code == 1
    assert "No such backup file" in result.output


def test_db_migrate_command() -> None:
    result = runner.invoke(app, ["db", "migrate"])
    assert result.exit_code == 0, result.output


def test_account_set_access_token() -> None:
    _create()

    result = runner.invoke(
        app,
        [
            "account",
            "set",
            "access-token",
            "@bot:example.org",
            "--access-token",
            "tok123",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Updated access token" in result.output

    from matrix_jitsi_bot.db.models import Account

    assert Account.objects.get(user_id="@bot:example.org").access_token == "tok123"


def test_account_set_device_id() -> None:
    _create()

    result = runner.invoke(
        app, ["account", "set", "device-id", "@bot:example.org", "DEVICE1"]
    )
    assert result.exit_code == 0, result.output

    from matrix_jitsi_bot.db.models import Account

    assert Account.objects.get(user_id="@bot:example.org").device_id == "DEVICE1"


def test_account_set_unknown_account_fails() -> None:
    result = runner.invoke(
        app, ["account", "set", "password", "@nobody:example.org", "--password", "x"]
    )
    assert result.exit_code == 1
    assert "No such account" in result.output


def test_account_set_display_name(monkeypatch) -> None:
    _create()

    calls = []

    async def _fake_set_display_name(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr("matrix_jitsi_bot.bot.set_display_name", _fake_set_display_name)

    result = runner.invoke(
        app, ["account", "set", "display-name", "@bot:example.org", "Jitsi Bot"]
    )
    assert result.exit_code == 0, result.output
    assert "Updated display name" in result.output
    assert calls[0]["display_name"] == "Jitsi Bot"
    assert calls[0]["user_id"] == "@bot:example.org"


def test_account_set_display_name_failure(monkeypatch) -> None:
    _create()

    from matrix_jitsi_bot.matrix_login import LoginFailed

    async def _fail(**_kwargs):
        raise LoginFailed("401: bad credentials")

    monkeypatch.setattr("matrix_jitsi_bot.bot.set_display_name", _fail)

    result = runner.invoke(
        app, ["account", "set", "display-name", "@bot:example.org", "Jitsi Bot"]
    )
    assert result.exit_code == 1
    assert "401" in result.output


def test_account_set_display_name_unknown_account_fails() -> None:
    result = runner.invoke(
        app, ["account", "set", "display-name", "@nobody:example.org", "Name"]
    )
    assert result.exit_code == 1
    assert "No such account" in result.output


def test_account_set_avatar(monkeypatch, tmp_path) -> None:
    _create()

    image = tmp_path / "logo.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")

    calls = []

    async def _fake_set_avatar(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr("matrix_jitsi_bot.bot.set_avatar", _fake_set_avatar)

    result = runner.invoke(
        app, ["account", "set", "avatar", "@bot:example.org", str(image)]
    )
    assert result.exit_code == 0, result.output
    assert "Updated avatar" in result.output
    assert calls[0]["image_path"] == image


def test_account_set_avatar_missing_file_fails() -> None:
    _create()

    result = runner.invoke(
        app, ["account", "set", "avatar", "@bot:example.org", "/no/such/file.png"]
    )
    assert result.exit_code == 1
    assert "No such file" in result.output


def test_account_check_success(monkeypatch) -> None:
    _create()

    from matrix_jitsi_bot.matrix_login import LoginCheckResult

    async def _ok(**_kwargs):
        return LoginCheckResult(message="Logged in as @bot:example.org")

    async def _cross_signed(**_kwargs):
        return True

    monkeypatch.setattr("matrix_jitsi_bot.bot.check_login", _ok)
    monkeypatch.setattr("matrix_jitsi_bot.bot.has_cross_signing", _cross_signed)

    result = runner.invoke(app, ["account", "check", "@bot:example.org"])
    assert result.exit_code == 0, result.output
    assert "Logged in as @bot:example.org" in result.output
    assert "cross-signing" not in result.output


def test_account_check_warns_about_missing_cross_signing(monkeypatch) -> None:
    _create()

    from matrix_jitsi_bot.matrix_login import LoginCheckResult

    async def _ok(**_kwargs):
        return LoginCheckResult(message="Logged in as @bot:example.org")

    async def _not_cross_signed(**_kwargs):
        return False

    monkeypatch.setattr("matrix_jitsi_bot.bot.check_login", _ok)
    monkeypatch.setattr("matrix_jitsi_bot.bot.has_cross_signing", _not_cross_signed)

    result = runner.invoke(app, ["account", "check", "@bot:example.org"])
    assert result.exit_code == 0, result.output
    assert "no cross-signing identity set up" in result.output


def test_account_check_failure(monkeypatch) -> None:
    _create()

    from matrix_jitsi_bot.matrix_login import LoginFailed

    async def _fail(**_kwargs):
        raise LoginFailed("401: bad credentials")

    monkeypatch.setattr("matrix_jitsi_bot.bot.check_login", _fail)

    result = runner.invoke(app, ["account", "check", "@bot:example.org"])
    assert result.exit_code == 1
    assert "401" in result.output


def test_account_check_unknown_account_fails() -> None:
    result = runner.invoke(app, ["account", "check", "@nobody:example.org"])
    assert result.exit_code == 1
    assert "No such account" in result.output


def test_account_create_test_failure_does_not_save(monkeypatch) -> None:
    from matrix_jitsi_bot.matrix_login import LoginFailed

    async def _fail(**_kwargs):
        raise LoginFailed("401: bad credentials")

    monkeypatch.setattr("matrix_jitsi_bot.bot.check_login", _fail)

    # Deliberately not `_create()` - this needs `test=True` (the default),
    # to actually exercise the mocked login-check failure.
    result = runner.invoke(
        app,
        [
            "account",
            "create",
            "@bot:example.org",
            "--homeserver",
            "https://example.org",
            "--password",
            "wrong",
        ],
    )
    assert result.exit_code == 1
    assert "401" in result.output

    result = runner.invoke(app, ["account", "list"])
    assert "No accounts configured." in result.output


def test_run_with_no_accounts_fails() -> None:
    result = runner.invoke(app, ["run"])
    assert result.exit_code == 1
    assert "No accounts configured" in result.output


def test_run_with_multiple_accounts_requires_user_id() -> None:
    _create("@a:example.org")
    _create("@b:example.org")

    result = runner.invoke(app, ["run"])
    assert result.exit_code == 1
    assert "Multiple accounts configured" in result.output


def test_run_once_with_no_accounts_fails() -> None:
    result = runner.invoke(app, ["run", "--once"])
    assert result.exit_code == 1
    assert "No accounts configured" in result.output


def test_run_once_prints_the_checked_count(monkeypatch) -> None:
    _create()

    async def _fake_run_once(self, user_id=None):
        return 3

    monkeypatch.setattr("matrix_jitsi_bot.bot.MatrixJitsiBot.run_once", _fake_run_once)

    result = runner.invoke(app, ["run", "--once"])

    assert result.exit_code == 0, result.output
    assert "Checked 3 conferences." in result.output


def test_run_once_prints_singular_for_one_conference(monkeypatch) -> None:
    _create()

    async def _fake_run_once(self, user_id=None):
        return 1

    monkeypatch.setattr("matrix_jitsi_bot.bot.MatrixJitsiBot.run_once", _fake_run_once)

    result = runner.invoke(app, ["run", "--once"])

    assert result.exit_code == 0, result.output
    assert "Checked 1 conference." in result.output


def test_configure_logging_defaults_to_info() -> None:
    import logging

    from matrix_jitsi_bot.cli import _configure_logging

    _configure_logging(0)

    assert logging.getLogger().getEffectiveLevel() == logging.INFO
    assert logging.getLogger("matrix_jitsi_bot").getEffectiveLevel() == logging.INFO
    assert logging.getLogger("nio").getEffectiveLevel() == logging.INFO


def test_configure_logging_dash_v_is_debug_for_matrix_jitsi_bot_only() -> None:
    """`-v` must not leak DEBUG logging into dependencies (nio, niobot,
    and whatever *they* pull in - websockets, urllib3, ...) - only
    raising the root logger's own level did exactly that, since every
    logger without its own explicit level inherits from it.
    """
    import logging

    from matrix_jitsi_bot.cli import _configure_logging

    _configure_logging(1)

    assert logging.getLogger().getEffectiveLevel() == logging.INFO
    assert logging.getLogger("matrix_jitsi_bot").getEffectiveLevel() == logging.DEBUG
    assert (
        logging.getLogger("matrix_jitsi_bot.bot").getEffectiveLevel() == logging.DEBUG
    )
    assert logging.getLogger("nio").getEffectiveLevel() == logging.INFO
    assert logging.getLogger("websockets").getEffectiveLevel() == logging.INFO


def test_configure_logging_dash_v_v_includes_dependencies() -> None:
    import logging

    from matrix_jitsi_bot.cli import _configure_logging

    _configure_logging(2)

    assert logging.getLogger().getEffectiveLevel() == logging.DEBUG
    assert logging.getLogger("nio").getEffectiveLevel() == logging.DEBUG
    assert logging.getLogger("websockets").getEffectiveLevel() == logging.DEBUG


def test_status_with_no_rooms() -> None:
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0, result.output
    assert "No rooms." in result.output


def test_status_lists_rooms_moderators_and_tracked_conferences() -> None:
    from datetime import UTC, datetime

    from matrix_jitsi_bot.db.models import (
        Conversation,
        JitsiRoom,
        Message,
        Room,
        RoomMember,
        TrackedJitsiRoom,
    )

    room = Room.objects.create(room_id="!room:example.org")
    RoomMember.objects.create(room=room, user_id="@mod:example.org", power_level=50)
    conv = Conversation.objects.create(room=room)
    Message.objects.create(
        conversation=conv,
        sender="@a:example.org",
        event_id="$1",
        body="hi",
        server_timestamp=datetime.now(tz=UTC),
    )
    jitsi_room = JitsiRoom.objects.create(
        url="https://meet.example.org/Room", is_open=True, participants=["Alice"]
    )
    TrackedJitsiRoom.objects.create(room=room, jitsi_room=jitsi_room, track_open=True)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0, result.output
    assert "!room:example.org" in result.output
    assert "@mod:example.org" in result.output
    assert "https://meet.example.org/Room: open" in result.output


def test_status_shows_a_freshly_joined_room_with_no_messages_yet() -> None:
    """A room the bot just joined has no `Conversation` yet - only
    created lazily on the first message - but should still be listed,
    not silently excluded from `status`.
    """
    from matrix_jitsi_bot.db.models import Room

    Room.objects.create(room_id="!brandnew:example.org")

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0, result.output
    assert "!brandnew:example.org" in result.output
    assert "(nothing tracked)" in result.output


def test_status_shows_rooms_with_nothing_tracked() -> None:
    from matrix_jitsi_bot.db.models import Conversation, Room

    room = Room.objects.create(room_id="!quiet:example.org")
    Conversation.objects.create(room=room)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0, result.output
    assert "!quiet:example.org" in result.output
    assert "(nothing tracked)" in result.output


def test_status_groups_rooms_by_account() -> None:
    from matrix_jitsi_bot.db.models import Account, Room

    account_a = Account.objects.create(
        user_id="@a:example.org", homeserver="https://example.org"
    )
    account_b = Account.objects.create(
        user_id="@b:example.org", homeserver="https://example.org"
    )
    Room.objects.create(room_id="!a-room:example.org", account=account_a)
    Room.objects.create(room_id="!b-room:example.org", account=account_b)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0, result.output
    a_index = result.output.index("Account: @a:example.org")
    a_room_index = result.output.index("!a-room:example.org")
    b_index = result.output.index("Account: @b:example.org")
    b_room_index = result.output.index("!b-room:example.org")
    assert a_index < a_room_index < b_index < b_room_index


def test_status_lists_an_account_with_no_rooms() -> None:
    from matrix_jitsi_bot.db.models import Account

    Account.objects.create(
        user_id="@lonely:example.org", homeserver="https://example.org"
    )

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0, result.output
    assert "Account: @lonely:example.org" in result.output
    assert "(no rooms)" in result.output
