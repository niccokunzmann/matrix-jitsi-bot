"""End-to-end scenarios across the whole bot: a chat message comes in, we
check the database, a Jitsi conference's status changes behind the
scenes, another message comes in, we check the database again.

The Matrix side (the `nio`/`niobot` client) and the Jitsi side
(`inspect_jitsi`, via `matrix_jitsi_bot.jitsi.check_jitsi_room`) are both
mocked - nothing here touches the network.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from matrix_jitsi_bot.bot import MatrixJitsiBot
from matrix_jitsi_bot.db.models import (
    CommandReply,
    JitsiRoom,
    Room,
    RoomMember,
    TrackedJitsiRoom,
)
from matrix_jitsi_bot.interactions import AllInteractions
from matrix_jitsi_bot.jitsi import JitsiStatus

_JITSI_URL = "https://meet.example.org/Room"


def _fake_client() -> MagicMock:
    client = MagicMock(user_id="@bot:example.org")
    client.send_message = AsyncMock()
    client.room_leave = AsyncMock()
    client.add_reaction = AsyncMock()
    return client


def _fake_room(room_id: str) -> MagicMock:
    room = MagicMock(room_id=room_id)
    room.name = "Team chat"
    return room


def _fake_event(
    event_id: str, body: str, sender: str = "@mod:example.org"
) -> MagicMock:
    return MagicMock(
        sender=sender,
        body=body,
        event_id=event_id,
        server_timestamp=0,
        source={},
    )


def test_track_check_and_status_change_flow(monkeypatch) -> None:
    interaction = AllInteractions()
    bot = MatrixJitsiBot(interaction)
    client = _fake_client()
    fake_room = _fake_room("!room:example.org")

    # -- database setup: the room already exists, with a synced --
    # -- moderator - as if `_sync_room_members` had already run. --
    room = Room.objects.create(room_id="!room:example.org")
    RoomMember.objects.create(room=room, user_id="@mod:example.org", power_level=50)

    # 1. The moderator mentions the bot to start tracking a conference.
    event = _fake_event("$1", f"@bot:example.org: track status of {_JITSI_URL}")
    asyncio.run(interaction.on_matrix_message(client, fake_room, event))

    # -- database check: the conference is now tracked in this room. --
    tracked = TrackedJitsiRoom.objects.get(room=room)
    assert tracked.jitsi_room.url == _JITSI_URL
    assert client.send_message.await_args.args[1] == f"Now tracking {_JITSI_URL}."

    # 2. Behind the scenes, the conference opens - simulate a check
    #    finding it open, without any chat message being involved. Only
    #    status is tracked here, so participants shouldn't be fetched.
    async def _opens(url: str, *, want_participants: bool) -> JitsiStatus:
        assert url == _JITSI_URL
        assert want_participants is False
        return JitsiStatus(is_open=True, participants=None)

    monkeypatch.setattr("matrix_jitsi_bot.jitsi.check_jitsi_room", _opens)
    client.send_message.reset_mock()
    asyncio.run(bot.poll_jitsi_rooms_once(client))

    # -- database check: the conference is now recorded as open, --
    # -- and the tracking room was told about it.                --
    tracked.jitsi_room.refresh_from_db()
    assert tracked.jitsi_room.is_open is True
    assert tracked.jitsi_room.participants == []
    client.send_message.assert_awaited_once_with(
        "!room:example.org", f"Conference {_JITSI_URL} started"
    )

    # 3. A room member asks for the status inline, from the same room.
    client.send_message.reset_mock()
    event = _fake_event("$2", "@bot:example.org: status", sender="@anyone:example.org")
    asyncio.run(interaction.on_matrix_message(client, fake_room, event))

    reply_text = client.send_message.await_args.args[1]
    assert reply_text == f"{_JITSI_URL}: open, empty"

    # -- database check: asking for status didn't create a duplicate --
    # -- CommandReply per conference, just the one for this message. --
    assert CommandReply.objects.filter(message__event_id="$2").count() == 1

    # 4. Behind the scenes, the conference closes.
    async def _closes(url: str, *, want_participants: bool) -> JitsiStatus:
        return JitsiStatus(is_open=False, participants=[])

    monkeypatch.setattr("matrix_jitsi_bot.jitsi.check_jitsi_room", _closes)
    tracked.jitsi_room.next_check_at = tracked.jitsi_room.last_checked_at
    tracked.jitsi_room.save(update_fields=["next_check_at"])
    client.send_message.reset_mock()
    asyncio.run(bot.poll_jitsi_rooms_once(client))

    # -- database check: closed, and told about it again. --
    tracked.jitsi_room.refresh_from_db()
    assert tracked.jitsi_room.is_open is False
    client.send_message.assert_awaited_once_with(
        "!room:example.org", f"Conference {_JITSI_URL} ended"
    )

    # 5. The moderator stops tracking it.
    client.send_message.reset_mock()
    event = _fake_event("$3", f"@bot:example.org: don't track {_JITSI_URL}")
    asyncio.run(interaction.on_matrix_message(client, fake_room, event))

    # -- database check: nothing tracked in this room any more, but --
    # -- the conference itself is still remembered.                 --
    assert not TrackedJitsiRoom.objects.filter(room=room).exists()
    assert JitsiRoom.objects.filter(url=_JITSI_URL).exists()


def test_bot_does_not_reply_to_a_message_addressed_to_somebody_else() -> None:
    """Regression test for a real bug: through the full
    `on_matrix_message` pipeline (which sets `bot_user_id` from the
    live client - see `BotInteraction.bot_user_id`), a message
    addressed to a different Matrix user must not be mistaken for a
    mention of the bot, even though its first word is address-shaped.
    """
    interaction = AllInteractions()
    client = _fake_client()
    fake_room = _fake_room("!room:example.org")

    event = _fake_event(
        "$1", "@someone-else:example.org: hello", sender="@anyone:example.org"
    )
    asyncio.run(interaction.on_matrix_message(client, fake_room, event))

    client.send_message.assert_not_awaited()


def test_greeting_pause_and_leave_flow_via_all_interactions() -> None:
    """Exercises `GreetingInteraction`, `RoomInteraction`, and
    `HelpInteraction` together through `AllInteractions` - the same
    composition that caught a bug where a reaction called a private
    helper method on `self` that only existed on the class it was
    declared in, not on whatever interaction ends up dispatching it.
    """
    interaction = AllInteractions()
    client = _fake_client()
    fake_room = _fake_room("!room:example.org")

    room = Room.objects.create(room_id="!room:example.org")
    RoomMember.objects.create(room=room, user_id="@mod:example.org", power_level=50)

    # 1. A friendly greeting works, unaddressed by anything else.
    event = _fake_event("$1", "@bot:example.org: hello", sender="@anyone:example.org")
    asyncio.run(interaction.on_matrix_message(client, fake_room, event))
    assert client.send_message.await_args.args[1] == "Hello!"

    # -- database check: recorded, nothing tracked yet. --
    assert not TrackedJitsiRoom.objects.filter(room=room).exists()

    # 2. Something nobody understands falls through to the help reaction.
    client.send_message.reset_mock()
    event = _fake_event("$2", "@bot:example.org: do a barrel roll")
    asyncio.run(interaction.on_matrix_message(client, fake_room, event))
    assert "don't understand" in client.send_message.await_args.args[1]

    # 3. The moderator pauses the room.
    client.send_message.reset_mock()
    event = _fake_event("$3", "@bot:example.org: pause tracking")
    asyncio.run(interaction.on_matrix_message(client, fake_room, event))
    assert client.send_message.await_args.args[1] == "Tracking paused."

    # -- database check: paused. --
    room.refresh_from_db()
    assert room.paused is True

    # 4. While paused, even a friendly greeting is blocked.
    client.send_message.reset_mock()
    event = _fake_event("$4", "@bot:example.org: hello", sender="@anyone:example.org")
    asyncio.run(interaction.on_matrix_message(client, fake_room, event))
    assert "paused" in client.send_message.await_args.args[1]

    # 5. Unpausing still works while paused.
    client.send_message.reset_mock()
    event = _fake_event("$5", "@bot:example.org: unpause tracking")
    asyncio.run(interaction.on_matrix_message(client, fake_room, event))
    assert client.send_message.await_args.args[1] == "Tracking resumed."
    room.refresh_from_db()
    assert room.paused is False

    # 6. The moderator makes the bot leave.
    client.send_message.reset_mock()
    event = _fake_event("$6", "@bot:example.org: leave")
    asyncio.run(interaction.on_matrix_message(client, fake_room, event))
    assert client.send_message.await_args.args[1] == "Leaving this room now. Goodbye!"

    # -- database check: `bot.py`'s `_leave_if_flagged` acted on the --
    # -- flag once the reply above was sent - left, and forgotten.  --
    client.room_leave.assert_awaited_once_with("!room:example.org")
    assert not Room.objects.filter(room_id="!room:example.org").exists()
