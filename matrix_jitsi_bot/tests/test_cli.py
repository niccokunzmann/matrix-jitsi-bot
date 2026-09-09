from typer.testing import CliRunner

from matrix_jitsi_bot.cli import app

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip()


def test_account_create_list_show_remove() -> None:
    result = runner.invoke(
        app,
        [
            "account",
            "create",
            "@bot:example.org",
            "--homeserver",
            "https://example.org",
            "--password",
            "secret",
            "--no-test",
        ],
    )
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


def test_account_show_unknown_account_fails() -> None:
    result = runner.invoke(app, ["account", "show", "@nobody:example.org"])
    assert result.exit_code == 1
    assert "No such account" in result.output


def test_account_set_password() -> None:
    runner.invoke(
        app,
        [
            "account",
            "create",
            "@bot:example.org",
            "--homeserver",
            "https://example.org",
            "--password",
            "secret",
            "--no-test",
        ],
    )

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
    runner.invoke(
        app,
        [
            "account",
            "create",
            "@bot:example.org",
            "--homeserver",
            "https://example.org",
            "--password",
            "secret",
            "--no-test",
        ],
    )

    result = runner.invoke(
        app,
        ["account", "set", "homeserver", "@bot:example.org", "https://new.example.org"],
    )
    assert result.exit_code == 0, result.output

    from matrix_jitsi_bot.db.models import Account

    account = Account.objects.get(user_id="@bot:example.org")
    assert account.homeserver == "https://new.example.org"


def test_db_backup_and_restore(tmp_path) -> None:
    runner.invoke(
        app,
        [
            "account",
            "create",
            "@bot:example.org",
            "--homeserver",
            "https://example.org",
            "--password",
            "secret",
            "--no-test",
        ],
    )

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


def _create(user_id: str = "@bot:example.org") -> None:
    runner.invoke(
        app,
        [
            "account",
            "create",
            user_id,
            "--homeserver",
            "https://example.org",
            "--password",
            "secret",
            "--no-test",
        ],
    )


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


def test_account_check_success(monkeypatch) -> None:
    _create()

    from matrix_jitsi_bot.matrix_login import LoginCheckResult

    async def _ok(**_kwargs):
        return LoginCheckResult(message="Logged in as @bot:example.org")

    monkeypatch.setattr("matrix_jitsi_bot.bot.check_login", _ok)

    result = runner.invoke(app, ["account", "check", "@bot:example.org"])
    assert result.exit_code == 0, result.output
    assert "Logged in as @bot:example.org" in result.output


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


def test_configure_logging_defaults_to_info() -> None:
    import logging

    from matrix_jitsi_bot.cli import _configure_logging

    _configure_logging(0)

    assert logging.getLogger().getEffectiveLevel() == logging.INFO
    assert logging.getLogger("nio").getEffectiveLevel() == logging.WARNING


def test_configure_logging_dash_v_is_debug_but_keeps_dependencies_quiet() -> None:
    import logging

    from matrix_jitsi_bot.cli import _configure_logging

    _configure_logging(1)

    assert logging.getLogger().getEffectiveLevel() == logging.DEBUG
    assert logging.getLogger("nio").getEffectiveLevel() == logging.WARNING


def test_configure_logging_dash_v_v_includes_dependencies() -> None:
    import logging

    from matrix_jitsi_bot.cli import _configure_logging

    _configure_logging(2)

    assert logging.getLogger().getEffectiveLevel() == logging.DEBUG
    assert logging.getLogger("nio").getEffectiveLevel() == logging.DEBUG
