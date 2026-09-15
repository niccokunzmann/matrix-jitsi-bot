"""Tests for a Matrix room's stored display name: `Room.name` itself,
how it's kept in sync from `nio` events, `Room.label()`'s formatting
(including control-character escaping - a room name is attacker-
controlled), and `matrix-jitsi-bot status` showing both the label and
what's tracked in each room.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from typer.testing import CliRunner

from matrix_jitsi_bot.bot import (
    MatrixJitsiBot,
    _register_room_on_invite,
    _sync_room_members,
    _sync_room_name,
)
from matrix_jitsi_bot.cli import app
from matrix_jitsi_bot.db.models import Room
from matrix_jitsi_bot.db.models.room import _escape_control_characters

runner = CliRunner()


@pytest.fixture
def fake_room():
    """A `nio` room stand-in, mirroring `test_bot.py`'s own fixture."""
    room = MagicMock(room_id="!room:example.org")
    room.name = (
        "Team chat"  # `name=` in the constructor sets the mock's own repr, not this
    )
    return room


@pytest.fixture
def fake_client():
    client = MagicMock(user_id="@bot:example.org")
    client.send_message = AsyncMock()
    client.room_leave = AsyncMock()
    return client


@pytest.fixture
def fake_account():
    from matrix_jitsi_bot.db.models import Account

    return Account.objects.create(
        user_id="@bot:example.org", homeserver="https://example.org"
    )


# -- _escape_control_characters ---------------------------------------------


def test_escape_control_characters_leaves_printable_text_alone() -> None:
    assert _escape_control_characters("Team chat 🎉") == "Team chat 🎉"


def test_escape_control_characters_escapes_common_whitespace() -> None:
    assert _escape_control_characters("line1\nline2\ttab\rcr") == (
        "line1\\nline2\\ttab\\rcr"
    )


def test_escape_control_characters_escapes_a_literal_backslash() -> None:
    r"""Without this, an escaped newline (`\\n`) would be indistinguishable
    from a literal backslash-n in the original name.
    """
    assert _escape_control_characters("back\\slash") == "back\\\\slash"


def test_escape_control_characters_escapes_other_control_characters() -> None:
    assert _escape_control_characters("bell\x07end") == "bell\\x07end"


# -- Room.update_name / update_name_of ---------------------------------------


def test_update_name_sets_the_name() -> None:
    room = Room.objects.create(room_id="!room:example.org")

    room.update_name("Team chat")

    room.refresh_from_db()
    assert room.name == "Team chat"


def test_update_name_treats_none_as_empty() -> None:
    room = Room.objects.create(room_id="!room:example.org", name="Old name")

    room.update_name(None)

    room.refresh_from_db()
    assert room.name == ""


def test_update_name_is_a_noop_when_unchanged() -> None:
    room = Room.objects.create(room_id="!room:example.org", name="Team chat")

    room.update_name("Team chat")  # would error if it tried to write a stale instance

    room.refresh_from_db()
    assert room.name == "Team chat"


def test_update_name_of_creates_the_room_if_missing() -> None:
    Room.update_name_of("!new:example.org", "Brand New")

    room = Room.objects.get(room_id="!new:example.org")
    assert room.name == "Brand New"


# -- Room.label ---------------------------------------------------------------


def test_label_is_just_the_room_id_without_a_name() -> None:
    room = Room.objects.create(room_id="!kbdVNZeuYWqpMIiXAg:chat.pycal.org")

    assert room.label() == "!kbdVNZeuYWqpMIiXAg:chat.pycal.org"


def test_label_combines_name_and_room_id_when_named() -> None:
    room = Room.objects.create(
        room_id="!kbdVNZeuYWqpMIiXAg:chat.pycal.org", name="pycal"
    )

    assert room.label() == '"pycal"(!kbdVNZeuYWqpMIiXAg:chat.pycal.org)'


def test_label_escapes_control_characters_in_the_name() -> None:
    """A room name with a literal newline can't be allowed to inject a
    fake extra line into `status`'s single-line-per-room output.
    """
    room = Room.objects.create(
        room_id="!room:example.org", name="evil\nConference https://x ended"
    )

    assert room.label() == '"evil\\nConference https://x ended"(!room:example.org)'
    assert "\n" not in room.label()


# -- syncing the name from nio events -----------------------------------------


def test_register_room_on_invite_stores_the_room_name(
    fake_room, fake_client, fake_account
) -> None:
    event = MagicMock(state_key="@bot:example.org")

    asyncio.run(_register_room_on_invite(fake_client, fake_account, fake_room, event))

    room = Room.objects.get(room_id="!room:example.org")
    assert room.name == "Team chat"


def test_sync_room_members_updates_the_room_name(fake_room, fake_account) -> None:
    Room.objects.create(room_id="!room:example.org", name="Old name")
    fake_room.users = {"@a:example.org": None}
    fake_room.invited_users = {}
    fake_room.power_levels.get_user_level.return_value = 0
    event = MagicMock(state_key="@a:example.org", membership="join")

    asyncio.run(_sync_room_members(fake_account, fake_room, event))

    room = Room.objects.get(room_id="!room:example.org")
    assert room.name == "Team chat"


def test_sync_room_name_updates_an_explicit_rename(fake_room) -> None:
    """A bare rename (no membership change) is its own `nio.RoomNameEvent`
    - `_sync_room_members` alone wouldn't see it.
    """
    Room.objects.create(room_id="!room:example.org", name="Old name")
    fake_room.name = "New name"
    event = MagicMock()  # unused - `_sync_room_name` reads `room.name`, not the event

    asyncio.run(_sync_room_name(fake_room, event))

    room = Room.objects.get(room_id="!room:example.org")
    assert room.name == "New name"


def test_reconcile_joined_rooms_refreshes_the_name_of_an_existing_room(
    fake_client, fake_account
) -> None:
    Room.objects.create(room_id="!room:example.org", name="Old name")
    nio_room = MagicMock()
    nio_room.name = "New name"  # see fake_room's own note on `name=`
    fake_client.rooms = {"!room:example.org": nio_room}

    asyncio.run(MatrixJitsiBot.reconcile_joined_rooms(fake_client, fake_account))

    room = Room.objects.get(room_id="!room:example.org")
    assert room.name == "New name"


# -- `matrix-jitsi-bot status` ------------------------------------------------


def test_status_shows_the_room_label_with_its_name() -> None:
    Room.objects.create(room_id="!room:example.org", name="pycal")

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0, result.output
    assert '"pycal"(!room:example.org)' in result.output


def test_status_falls_back_to_the_bare_room_id_without_a_name() -> None:
    Room.objects.create(room_id="!room:example.org")

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0, result.output
    assert "!room:example.org" in result.output
    assert '"' not in result.output


def test_status_shows_what_is_tracked_for_each_conference() -> None:
    from matrix_jitsi_bot.db.models import JitsiRoom, TrackedJitsiRoom

    room = Room.objects.create(room_id="!room:example.org")
    jitsi_room = JitsiRoom.objects.create(url="https://meet.example.org/Room")
    TrackedJitsiRoom.objects.create(
        room=room, jitsi_room=jitsi_room, track_open=True, track_leaves=True
    )

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0, result.output
    assert "tracking: open, leaves" in result.output


def test_status_shows_a_dash_when_a_tracked_row_tracks_nothing() -> None:
    """Shouldn't happen in practice - an all-`False` row is deleted, see
    `TrackedJitsiRoom.is_tracking_anything` - but `status` reads a raw
    DB snapshot, so it shouldn't crash on one either.
    """
    from matrix_jitsi_bot.db.models import JitsiRoom, TrackedJitsiRoom

    room = Room.objects.create(room_id="!room:example.org")
    jitsi_room = JitsiRoom.objects.create(url="https://meet.example.org/Room")
    TrackedJitsiRoom.objects.create(room=room, jitsi_room=jitsi_room)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0, result.output
    assert "tracking: -" in result.output
