import asyncio
import itertools

import pytest

from matrix_jitsi_bot.django import setup_django

# Configure Django as soon as pytest loads this file - before it collects
# (imports) any test module. Without this, whether a test module can
# import `matrix_jitsi_bot.db.models` at its own module level depended on
# some *other*, unrelated test module happening to be collected first and
# configuring Django as a side effect (e.g. `test_cli.py`, whose
# `MatrixJitsiBot()` does this) - fragile, and silently broke running any
# subset of tests that left such a module out.
setup_django()


@pytest.fixture(autouse=True)
def _isolated_database(tmp_path):
    """Point the Django ORM at a fresh, temporary SQLite database for each test."""
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


@pytest.fixture
def send_message():
    """A `send_message(body, ...)` function recording a message as if it
    had just arrived, and returning its `Conversation` - the usual setup
    a test needs before exercising a `BotInteraction`.
    """
    from datetime import UTC, datetime

    event_ids = itertools.count(1)

    def _send(
        body: str,
        *,
        room_id: str = "!room:example.org",
        sender: str = "@a:example.org",
    ):
        from matrix_jitsi_bot.db.models import Conversation, Message, Room

        room, _ = Room.objects.get_or_create(room_id=room_id)
        conversation, _ = Conversation.objects.get_or_create(room=room)
        Message.objects.create(
            conversation=conversation,
            sender=sender,
            event_id=f"$evt{next(event_ids)}",
            body=body,
            server_timestamp=datetime.now(tz=UTC),
        )
        return conversation

    return _send


@pytest.fixture
def make_moderator():
    """A `make_moderator(conversation, user_id)` function granting a user
    Moderator power level in a conversation's room.
    """

    def _make_moderator(conversation, user_id: str = "@mod:example.org") -> None:
        from matrix_jitsi_bot.db.models import RoomMember

        RoomMember.objects.update_or_create(
            room=conversation.room, user_id=user_id, defaults={"power_level": 50}
        )

    return _make_moderator
