import asyncio

import pytest

from matrix_jitsi_bot.django import setup_django


@pytest.fixture(autouse=True)
def _isolated_database(tmp_path):
    """Point the Django ORM at a fresh, temporary SQLite database for each test."""
    setup_django()

    from asgiref.sync import sync_to_async
    from django.conf import settings
    from django.core.management import call_command
    from django.db import connections

    settings.DATABASES["default"]["NAME"] = str(tmp_path / "test.sqlite3")
    # Account/room code called via sync_to_async runs on asgiref's dedicated
    # thread-sensitive worker thread, which caches its own Django connection
    # separate from this (main) thread's - close both, or that worker thread
    # keeps talking to the previous test's database.
    connections.close_all()
    asyncio.run(sync_to_async(connections.close_all)())

    call_command("migrate", verbosity=0)
    yield
    connections.close_all()
    asyncio.run(sync_to_async(connections.close_all)())
