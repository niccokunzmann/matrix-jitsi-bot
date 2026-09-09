"""Command line interface for the Matrix Jitsi Bot.

A thin wrapper around
:py:class:`~matrix_jitsi_bot.bot.MatrixJitsiBot` - see ``bot.py`` for
the actual behaviour, which is equally usable directly from Python.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import typer

from .bot import MatrixJitsiBot
from .matrix_login import LoginFailed
from .version import __version__

app = typer.Typer(
    name="matrix-jitsi-bot",
    help=(
        "Watch Jitsi conferences and report their status to Matrix chat "
        "rooms.\n\n"
        "Documentation: https://matrix-jitsi-bot.readthedocs.io\n\n"
        "Source code: https://github.com/niccokunzmann/matrix-jitsi-bot"
    ),
    no_args_is_help=True,
)
db_app = typer.Typer(
    help="""Manage the bot's SQLite database.
The default database is matrix-jitsi-bot.sqlite3.
"""
)
account_app = typer.Typer(help="Manage Matrix accounts the bot can log in as.")
account_set_app = typer.Typer(help="Update a single attribute of an existing account.")
app.add_typer(db_app, name="db")
app.add_typer(account_app, name="account")
account_app.add_typer(account_set_app, name="set")

bot = MatrixJitsiBot()


def _version_callback(*, value: bool) -> None:
    """Print the installed version and exit, if ``--version`` was given."""
    if value:
        typer.echo(__version__)
        raise typer.Exit


def _configure_logging(verbose: int) -> None:
    """Set up logging for the verbosity ``-v`` was given ``verbose`` times.

    0 (default): INFO everywhere.
    1 (``-v``): DEBUG for matrix-jitsi-bot's own logging only - e.g.
    every
    :py:class:`~matrix_jitsi_bot.interactions.base.BotInteraction`
    handling a message - by raising just the ``matrix_jitsi_bot``
    logger's own level, while the root logger (and everything under
    it that doesn't set its own level - nio, niobot, and whatever
    *they* pull in, like websockets or urllib3) stays at INFO.
    2+ (``-vv``): DEBUG globally, by raising the root logger's level
    instead - so dependencies get their debug logging too.
    """
    root_level = logging.DEBUG if verbose >= 2 else logging.INFO
    logging.basicConfig(
        level=root_level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        force=True,
    )
    own_level = logging.DEBUG if verbose >= 1 else logging.INFO
    logging.getLogger("matrix_jitsi_bot").setLevel(own_level)


def _verbose_option() -> int:
    """A ``-v``/``--verbose`` option, declared fresh everywhere it's used.

    Click only recognizes a parent command's options *before* the
    subcommand name (``matrix-jitsi-bot -v run``) - a plain top-level
    option can't also be given after it (``matrix-jitsi-bot run -v``).
    Commands where that position matters (e.g. ``run``, the
    long-running one) redeclare this and add their own count to the
    top-level one stored on the context by
    :py:func:`~matrix_jitsi_bot.cli.main`, rather than relying on it
    alone.
    """
    return typer.Option(
        0,
        "--verbose",
        "-v",
        count=True,
        help=(
            "Increase log verbosity: once for debug logging of "
            "matrix-jitsi-bot itself only, twice or more for debug "
            "logging globally, including dependencies. Default is "
            "info-level logging. Combines with -v given before the "
            "command name."
        ),
    )


def _complete_user_id(ctx, param, incomplete: str) -> list[str]:
    """Complete a Matrix user ID from the accounts already configured."""
    from matrix_jitsi_bot.db.models import Account

    return list(
        Account.objects.filter(user_id__startswith=incomplete).values_list(
            "user_id", flat=True
        )
    )


@app.callback()
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the version and exit.",
    ),
    verbose: int = _verbose_option(),
) -> None:
    """Top-level callback: configure logging, and stash ``verbose`` on
    the context for subcommands that redeclare their own ``-v``.
    """
    ctx.obj = verbose
    _configure_logging(verbose)


@app.command("run")
def run(
    ctx: typer.Context,
    user_id: str = typer.Argument(
        None,
        help="Matrix user ID to run as. Uses the only account if omitted.",
        shell_complete=_complete_user_id,
    ),
    wait: float = typer.Option(
        None,
        help=(
            "Seconds between checks for a due Jitsi conference. Defaults "
            "to the MJB_POLL_INTERVAL environment variable, or 1. "
            "Ignored with --once."
        ),
    ),
    once: bool = typer.Option(
        False,
        "--once",
        help=(
            "Check every tracked conference once - not just ones "
            "currently due - notify about anything that changed, then "
            "exit, instead of running forever."
        ),
    ),
    verbose: int = _verbose_option(),
) -> None:
    """Log in and run the bot's main loop until interrupted, or - with
    --once - check everything a single time and exit.
    """
    if verbose:
        _configure_logging((ctx.obj or 0) + verbose)
    try:
        if once:
            checked = asyncio.run(bot.run_once(user_id))
            typer.echo(f"Checked {checked} conference{'s' if checked != 1 else ''}.")
        else:
            asyncio.run(bot.run(user_id, wait=wait))
    except KeyboardInterrupt:
        typer.echo("Stopped.")
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


def _format_ago(when, now) -> str:
    """``"never"``, or how long before ``now`` a past ``when`` was,
    e.g. ``"5s ago"``.
    """
    if when is None:
        return "never"
    return f"{int((now - when).total_seconds())}s ago"


def _format_in(when, now) -> str:
    """How long after ``now`` a future ``when`` is, e.g. ``"5s"``, or
    ``"now"`` if it's due.
    """
    seconds = int((when - now).total_seconds())
    return "now" if seconds <= 0 else f"{seconds}s"


@app.command("status")
def status() -> None:
    """List every account, and every room it's in and what it's
    tracking there.

    Read from the database only - no network access, and Jitsi
    conference status is exactly as last observed by ``run``'s
    background polling. Rooms are listed with the most recently active
    first, within each account.
    """
    from datetime import UTC, datetime

    reports = bot.status_report()
    if not reports:
        typer.echo("No rooms.")
        return

    now = datetime.now(tz=UTC)
    for account_report in reports:
        typer.echo(f"Account: {account_report.user_id or '(unknown account)'}")
        if not account_report.rooms:
            typer.echo("  (no rooms)")
        for report in account_report.rooms:
            moderators = ", ".join(report.moderators) or "-"
            last_message = _format_ago(report.last_message_at, now)
            typer.echo(
                f"  {report.room_id}  moderators: {moderators}  "
                f"last message: {last_message}"
            )
            if not report.tracked:
                typer.echo("      (nothing tracked)")
            for tracked in report.tracked:
                state = "open" if tracked.is_open else "closed"
                checked = _format_ago(tracked.last_checked_at, now)
                next_check = _format_in(tracked.next_check_at, now)
                typer.echo(
                    f"      {tracked.url}: {state}  checked {checked}  "
                    f"next check in {next_check}"
                )


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
def account_show(
    user_id: str = typer.Argument(shell_complete=_complete_user_id),
) -> None:
    """Show details of one Matrix account."""
    account = _get_account_or_exit(user_id)
    typer.echo(f"user_id:      {account.user_id}")
    typer.echo(f"homeserver:   {account.homeserver}")
    typer.echo(f"device_id:    {account.device_id or '-'}")
    typer.echo(f"has_password: {bool(account.password)}")
    typer.echo(f"has_token:    {bool(account.access_token)}")
    typer.echo(f"created_at:   {account.created_at}")


@account_app.command("remove")
def account_remove(
    user_id: str = typer.Argument(shell_complete=_complete_user_id),
) -> None:
    """Remove a Matrix account."""
    if not bot.remove_account(user_id):
        typer.echo(f"No such account: {user_id}", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"Removed account {user_id}")


_CROSS_SIGNING_WARNING = (
    "Warning: this account has no cross-signing identity set up - other "
    "users will always see its devices (including this bot's) as "
    '"not verified by its owner". Set this up once from an ordinary '
    "Matrix client logged in as this account (e.g. Element's Settings "
    "> Security & Privacy)."
)


@account_app.command("check")
def account_check(
    user_id: str = typer.Argument(shell_complete=_complete_user_id),
) -> None:
    """Verify a saved account can still log in to its homeserver, and
    warn if it has no cross-signing identity set up (see the "End-to-
    end encryption" section of the hosting docs).
    """
    _get_account_or_exit(user_id)

    async def _check() -> tuple:
        """Run both checks in one event loop, rather than two separate
        ``asyncio.run`` calls.
        """
        result = await bot.check_account(user_id)
        cross_signed = await bot.check_account_cross_signing(user_id)
        return result, cross_signed

    try:
        result, cross_signed = asyncio.run(_check())
    except LoginFailed as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(result.message)
    if not cross_signed:
        typer.echo(_CROSS_SIGNING_WARNING, err=True)


def _get_account_or_exit(user_id: str):
    """Look up the account for ``user_id``, or print an error and exit
    with status 1 if there is none.
    """
    from django.core.exceptions import ObjectDoesNotExist

    try:
        return bot.get_account(user_id)
    except ObjectDoesNotExist as exc:
        typer.echo(f"No such account: {user_id}", err=True)
        raise typer.Exit(code=1) from exc


@account_set_app.command("password")
def account_set_password(
    user_id: str = typer.Argument(shell_complete=_complete_user_id),
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
    user_id: str = typer.Argument(shell_complete=_complete_user_id),
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
def account_set_homeserver(
    user_id: str = typer.Argument(shell_complete=_complete_user_id),
    homeserver: str = typer.Argument(),
) -> None:
    """Set an account's homeserver URL."""
    _get_account_or_exit(user_id)
    bot.set_account_homeserver(user_id, homeserver)
    typer.echo(f"Updated homeserver for {user_id}")


@account_set_app.command("device-id")
def account_set_device_id(
    user_id: str = typer.Argument(shell_complete=_complete_user_id),
    device_id: str = typer.Argument(),
) -> None:
    """Set an account's device ID."""
    _get_account_or_exit(user_id)
    bot.set_account_device_id(user_id, device_id)
    typer.echo(f"Updated device ID for {user_id}")


@account_set_app.command("display-name")
def account_set_display_name(
    user_id: str = typer.Argument(shell_complete=_complete_user_id),
    display_name: str = typer.Argument(help="The new Matrix profile display name."),
) -> None:
    """Set an account's Matrix profile display name.

    This is what most Matrix clients (Element included) insert when
    the account is @-mentioned via autocomplete, so it also affects
    what a chat message needs to say to address the bot.
    """
    _get_account_or_exit(user_id)
    try:
        asyncio.run(bot.set_account_display_name(user_id, display_name))
    except LoginFailed as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Updated display name for {user_id}")


@account_set_app.command("avatar")
def account_set_avatar(
    user_id: str = typer.Argument(shell_complete=_complete_user_id),
    image: Path = typer.Argument(help="Path to the image file to upload."),
) -> None:
    """Set an account's Matrix profile avatar (logo) from a local image file."""
    _get_account_or_exit(user_id)
    if not image.is_file():
        typer.echo(f"No such file: {image}", err=True)
        raise typer.Exit(code=1)
    try:
        asyncio.run(bot.set_account_avatar(user_id, image))
    except LoginFailed as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Updated avatar for {user_id}")


if __name__ == "__main__":
    app()
