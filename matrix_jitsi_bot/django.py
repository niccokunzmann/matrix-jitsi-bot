"""Django glue: settings bootstrap and raw SQLite database operations.

Kept separate from ``bot.py`` so
:py:class:`~matrix_jitsi_bot.bot.MatrixJitsiBot` deals only in bot
concepts (accounts, running) while this module deals in Django/SQLite
mechanics.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import django
from django.conf import settings


def setup_django() -> None:
    """Configure Django settings and populate the app registry, once."""
    if settings.configured:
        return
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "matrix_jitsi_bot.settings")
    django.setup()


def migrate() -> None:
    """Apply database migrations."""
    from django.core.management import call_command

    call_command("migrate")


def makemigrations() -> None:
    """Generate new database migrations for model changes."""
    from django.core.management import call_command

    call_command("makemigrations", "matrix_jitsi_bot")


def db_path() -> Path:
    """The path of the database currently configured in Django settings."""
    return Path(settings.DATABASES["default"]["NAME"])


def crypto_store_path() -> Path:
    """Directory holding the end-to-end encryption store (Olm/Megolm
    sessions and keys - one account's worth of state per Matrix
    device) that ``niobot``/``nio`` manage on disk, not through
    Django's ORM. Created if missing.

    Without this (passed as ``store_path`` when constructing the
    client - see
    :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot._build_client`),
    the bot can never decrypt a message sent in an encrypted room -
    it would see only an undecryptable ``m.room.encrypted`` event, and
    never dispatch the
    :py:class:`nio.events.room_events.RoomMessageText` callback
    everything else here depends on.
    """
    path = Path(settings.CRYPTO_STORE_PATH)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _resolve_relative_to_db(file: Path, path: Path) -> Path:
    """Resolve a backup file path, relative paths sit next to the default database."""
    if file.is_absolute():
        return file
    return path.parent / file


def _copy_sqlite_db(source: Path, destination: Path) -> None:
    """Copy the SQLite database at ``source`` to ``destination``, live."""
    source_conn = sqlite3.connect(source)
    try:
        dest_conn = sqlite3.connect(destination)
        try:
            source_conn.backup(dest_conn)
        finally:
            dest_conn.close()
    finally:
        source_conn.close()


def backup(file: Path) -> Path:
    """Back up the database to ``file``. Returns the resolved destination path."""
    path = db_path()
    destination = _resolve_relative_to_db(file, path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    _copy_sqlite_db(path, destination)
    return destination


def restore(file: Path) -> Path:
    """Restore the database from ``file``. Raises ``FileNotFoundError`` if missing."""
    path = db_path()
    source = _resolve_relative_to_db(file, path)
    if not source.exists():
        raise FileNotFoundError(source)

    from django.db import connections

    connections.close_all()
    path.parent.mkdir(parents=True, exist_ok=True)
    _copy_sqlite_db(source, path)
    return source
