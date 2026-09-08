"""Command line interface for the Matrix Jitsi Bot.

A thin wrapper around `MatrixJitsiBot` - see `bot.py` for the actual
behaviour, which is equally usable directly from Python.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from .bot import MatrixJitsiBot
from .matrix_login import LoginFailed
from .version import __version__

app = typer.Typer(
    name="matrix-jitsi-bot",
    help="Watch Jitsi conferences and report their status to Matrix chat rooms.",
    no_args_is_help=True,
)
db_app = typer.Typer(help="Manage the bot's SQLite database.")
account_app = typer.Typer(help="Manage Matrix accounts the bot can log in as.")
account_set_app = typer.Typer(help="Update a single attribute of an existing account.")
app.add_typer(db_app, name="db")
app.add_typer(account_app, name="account")
account_app.add_typer(account_set_app, name="set")

bot = MatrixJitsiBot()


def _version_callback(*, value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the version and exit.",
    ),
) -> None:
    pass


@app.command("run")
def run(
    user_id: str = typer.Argument(
        None,
        help="Matrix user ID to run as. Uses the only account if omitted.",
    ),
) -> None:
    """Log in and run the bot's main loop until interrupted."""
    try:
        asyncio.run(bot.run(user_id))
    except KeyboardInterrupt:
        typer.echo("Stopped.")
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


@db_app.command("migrate")
def db_migrate() -> None:
    """Apply database migrations."""
    bot.migrate()


@db_app.command("makemigrations")
def db_makemigrations() -> None:
    """Generate new database migrations for model changes."""
    bot.makemigrations()


@db_app.command("backup")
def db_backup(
    file: Path = typer.Argument(
        ...,
        help="Backup destination. Relative paths sit next to the default database.",
    ),
) -> None:
    """Back up the bot's SQLite database to a file."""
    destination = bot.backup(file)
    typer.echo(f"Backed up database to {destination}")


@db_app.command("restore")
def db_restore(
    file: Path = typer.Argument(
        ...,
        help="Backup file to restore. Relative paths sit next to the default database.",
    ),
) -> None:
    """Restore the bot's SQLite database from a backup file."""
    try:
        source = bot.restore(file)
    except FileNotFoundError as exc:
        typer.echo(f"No such backup file: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Restored database from {source}")


@account_app.command("create")
def account_create(
    user_id: str = typer.Argument(
        ..., help="The bot's Matrix user ID, e.g. @bot:matrix.org"
    ),
    homeserver: str = typer.Option(
        "",
        help=(
            "The Matrix homeserver URL, e.g. https://matrix.org. "
            "Defaults to https://<server name from user_id>."
        ),
    ),
    device_id: str = typer.Option(
        "", help="Matrix device ID, leave empty to have the homeserver assign one."
    ),
    password: str = typer.Option("", help="Matrix account password."),
    access_token: str = typer.Option(
        "", help="Matrix access token, used instead of a password."
    ),
    test: bool = typer.Option(
        True,
        "--test/--no-test",
        help="Verify the credentials against the homeserver before saving.",
    ),
) -> None:
    """Create or update a Matrix account the bot can log in as."""
    if not password and not access_token:
        password = typer.prompt("Password", hide_input=True)

    try:
        account, created = asyncio.run(
            bot.create_account(
                user_id,
                homeserver=homeserver,
                device_id=device_id,
                password=password,
                access_token=access_token,
                test=test,
            )
        )
    except LoginFailed as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"{'Created' if created else 'Updated'} account {account.user_id}")


@account_app.command("list")
def account_list() -> None:
    """List all configured Matrix accounts."""
    accounts = bot.list_accounts()
    if not accounts:
        typer.echo("No accounts configured.")
        return
    for account in accounts:
        device_id = account.device_id or "-"
        typer.echo(f"{account.user_id}  {account.homeserver}  device_id={device_id}")


@account_app.command("show")
def account_show(user_id: str) -> None:
    """Show details of one Matrix account."""
    account = _get_account_or_exit(user_id)
    typer.echo(f"user_id:      {account.user_id}")
    typer.echo(f"homeserver:   {account.homeserver}")
    typer.echo(f"device_id:    {account.device_id or '-'}")
    typer.echo(f"has_password: {bool(account.password)}")
    typer.echo(f"has_token:    {bool(account.access_token)}")
    typer.echo(f"created_at:   {account.created_at}")


@account_app.command("remove")
def account_remove(user_id: str) -> None:
    """Remove a Matrix account."""
    if not bot.remove_account(user_id):
        typer.echo(f"No such account: {user_id}", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"Removed account {user_id}")


@account_app.command("check")
def account_check(user_id: str) -> None:
    """Verify a saved account can still log in to its homeserver."""
    _get_account_or_exit(user_id)
    try:
        result = asyncio.run(bot.check_account(user_id))
    except LoginFailed as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(result.message)


def _get_account_or_exit(user_id: str):
    from django.core.exceptions import ObjectDoesNotExist

    try:
        return bot.get_account(user_id)
    except ObjectDoesNotExist as exc:
        typer.echo(f"No such account: {user_id}", err=True)
        raise typer.Exit(code=1) from exc


@account_set_app.command("password")
def account_set_password(
    user_id: str,
    password: str = typer.Option(None, help="New password. Prompts if omitted."),
) -> None:
    """Set an account's password."""
    _get_account_or_exit(user_id)
    if password is None:
        password = typer.prompt("Password", hide_input=True)
    bot.set_account_password(user_id, password)
    typer.echo(f"Updated password for {user_id}")


@account_set_app.command("access-token")
def account_set_access_token(
    user_id: str,
    access_token: str = typer.Option(
        None, help="New access token. Prompts if omitted."
    ),
) -> None:
    """Set an account's access token."""
    _get_account_or_exit(user_id)
    if access_token is None:
        access_token = typer.prompt("Access token", hide_input=True)
    bot.set_account_access_token(user_id, access_token)
    typer.echo(f"Updated access token for {user_id}")


@account_set_app.command("homeserver")
def account_set_homeserver(user_id: str, homeserver: str) -> None:
    """Set an account's homeserver URL."""
    _get_account_or_exit(user_id)
    bot.set_account_homeserver(user_id, homeserver)
    typer.echo(f"Updated homeserver for {user_id}")


@account_set_app.command("device-id")
def account_set_device_id(user_id: str, device_id: str) -> None:
    """Set an account's device ID."""
    _get_account_or_exit(user_id)
    bot.set_account_device_id(user_id, device_id)
    typer.echo(f"Updated device ID for {user_id}")


if __name__ == "__main__":
    app()
