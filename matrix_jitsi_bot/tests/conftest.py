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


@pytest.fixture(scope="session")
def _migrated_template(tmp_path_factory):
    """A database with every migration applied, made once per test run:
    migrating takes much longer than any test, so every test works on a
    copy of this - see ``_isolated_database``.
    """
    from django.conf import settings
    from django.core.management import call_command
    from django.db import connections

    template = tmp_path_factory.mktemp("template") / "template.sqlite3"
    settings.DATABASES["default"]["NAME"] = str(template)
    connections.close_all()
    call_command("migrate", verbosity=0)
    with connections["default"].cursor() as cursor:
        # Everything into the one file, so copying that file is enough.
        cursor.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    connections.close_all()
    return template


@pytest.fixture(autouse=True)
def _isolated_database(request, tmp_path):
    """Point the Django ORM at a fresh, temporary SQLite database for each
    test: a copy of the migrated template - unless the test is marked
    ``no_database``, as a test that never uses the database needs none,
    and that is checked: it fails if it does.
    """
    if request.node.get_closest_marker("no_database"):
        # Not the real database either: a marked test that uses one fails.
        from django.db.backends.base.base import BaseDatabaseWrapper

        def _refuse(self):
            msg = "a test marked no_database used the database"
            raise AssertionError(msg)

        request.getfixturevalue("monkeypatch").setattr(
            BaseDatabaseWrapper, "connect", _refuse
        )
        yield
        return

    import shutil

    from asgiref.sync import sync_to_async
    from django.conf import settings
    from django.db import connections

    template = request.getfixturevalue("_migrated_template")
    database = tmp_path / "test.sqlite3"
    shutil.copyfile(template, database)
    settings.DATABASES["default"]["NAME"] = str(database)
    # Account/room code called via sync_to_async runs on asgiref's dedicated
    # thread-sensitive worker thread, which caches its own Django connection
    # separate from this (main) thread's - close both, or that worker thread
    # keeps talking to the previous test's database.
    connections.close_all()
    asyncio.run(sync_to_async(connections.close_all)())
    yield
    connections.close_all()
    asyncio.run(sync_to_async(connections.close_all)())


@pytest.fixture(autouse=True)
def _default_check_jitsi_room(monkeypatch):
    """By default, every Jitsi URL checks out as a valid, closed
    conference - most tests aren't about
    :py:func:`~matrix_jitsi_bot.jitsi.check_jitsi_room` at all, and
    would otherwise need to mock it individually just to get a
    ``track`` command past
    :py:func:`~matrix_jitsi_bot.interactions.jitsi._verify_new_jitsi_room`'s
    initial check of a URL tracked for the first time. A test
    exercising a failing or specific check overrides this itself, via
    its own ``monkeypatch.setattr`` - applied after this fixture, so
    it wins.
    """
    from matrix_jitsi_bot.jitsi import JitsiStatus

    async def _default_check(
        url, *, want_participants=True, name=None, avatar_url=None
    ):
        return JitsiStatus(is_open=False, participants=None)

    monkeypatch.setattr("matrix_jitsi_bot.jitsi.check_jitsi_room", _default_check)


@pytest.fixture(autouse=True)
def _default_monitor_jitsi_room(monkeypatch):
    """By default, monitoring a Jitsi conference yields nothing and
    ends at once, without any network access - see
    :py:func:`~matrix_jitsi_bot.jitsi.monitor_jitsi_room`. A test of
    monitoring overrides this itself.
    """

    async def _default_monitor(url, *, name=None, avatar_url=None):
        return
        yield

    monkeypatch.setattr("matrix_jitsi_bot.jitsi.monitor_jitsi_room", _default_monitor)


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
