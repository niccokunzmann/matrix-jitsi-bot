"""End-to-end scenarios across the whole bot: a chat message comes in, we
check the database, a Jitsi conference's status changes behind the
scenes, another message comes in, we check the database again.

The Matrix side (the `nio`/`niobot` client) and the Jitsi side
(`inspect_jitsi`, via `matrix_jitsi_bot.jitsi.check_jitsi_room`) are both
mocked - nothing here touches the network.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

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


def _fake_room(room_id: str, *, bot_display_name: str | None = None) -> MagicMock:
    room = MagicMock(room_id=room_id)
    room.name = "Team chat"
    room.user_name = MagicMock(return_value=bot_display_name)
    room.users = {}
    room.invited_users = {}
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
    async def _opens(
        url: str,
        *,
        want_participants: bool,
        name: str | None = None,
        avatar_url: str | None = None,
    ) -> JitsiStatus:
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
    async def _closes(
        url: str,
        *,
        want_participants: bool,
        name: str | None = None,
        avatar_url: str | None = None,
    ) -> JitsiStatus:
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


@pytest.mark.no_database
def test_bot_does_not_reply_to_a_message_addressed_to_somebody_else() -> None:
    """Regression test for a real bug: through the full
    `on_matrix_message` pipeline (which sets `bot_names` from the live
    client and room - see `BotInteraction.bot_names`), a message
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


def test_bot_replies_when_addressed_by_its_room_display_name() -> None:
    """Regression test for a real outage: Element (and most Matrix
    clients) insert the mentioned account's *display name* - which can
    be completely unrelated to its user ID's localpart - as the plain-
    text leading word when picked from the mention autocomplete. A bot
    whose display name isn't literally its user ID's localpart must
    still be recognised as addressed, or it goes silent for everyone
    using that autocomplete - exactly what the single-word-only,
    localpart-or-full-ID check regressed to before `room.user_name(...)`
    was added to `BotInteraction.bot_names`.
    """
    interaction = AllInteractions()
    client = _fake_client()
    # Its display name ("Jitsi") is one word, distinct from both its
    # user ID and localpart ("bot") - `room.user_name(...)` is what
    # `BotInteraction.bot_names` actually consults for this.
    fake_room = _fake_room("!room:example.org", bot_display_name="Jitsi")

    room = Room.objects.create(room_id="!room:example.org")
    RoomMember.objects.create(room=room, user_id="@mod:example.org", power_level=50)

    event = _fake_event("$1", "Jitsi: hello", sender="@mod:example.org")
    asyncio.run(interaction.on_matrix_message(client, fake_room, event))

    assert client.send_message.await_args.args[1] == "Hello!"


@pytest.mark.parametrize("body", ["@jitsi-bot hello", "@jitsi-bot: hello"])
def test_bot_replies_when_addressed_as_at_its_display_name(body) -> None:
    """A command copied from the documentation - ``@jitsi-bot hello`` - works
    when ``jitsi-bot`` is the bot's display name in the chat, not its
    localpart, though the client did not turn it into a mention."""
    interaction = AllInteractions()
    client = _fake_client()
    fake_room = _fake_room("!room:example.org", bot_display_name="jitsi-bot")
    room = Room.objects.create(room_id="!room:example.org")
    RoomMember.objects.create(room=room, user_id="@mod:example.org", power_level=50)

    event = _fake_event("$1", body, sender="@mod:example.org")
    asyncio.run(interaction.on_matrix_message(client, fake_room, event))

    assert client.send_message.await_args.args[1] == "Hello!"


def _with_member(fake_room, user_id, display_name=None, *, invited=False) -> None:
    member = SimpleNamespace(user_id=user_id, display_name=display_name)
    (fake_room.invited_users if invited else fake_room.users)[user_id] = member


@pytest.mark.parametrize(
    ("other", "display_name", "invited"),
    [
        ("@bot:other.org", None, False),  # the same localpart on another server
        ("@alice:example.org", "BOT", False),  # the same display name
        ("@bot:other.org", None, True),  # invited, not yet in the chat
    ],
)
@pytest.mark.parametrize("body", ["@bot hello", "bot: hello", "@bot: hello"])
def test_bot_asks_to_be_mentioned_directly_if_its_name_is_shared(
    body, other, display_name, invited
) -> None:
    """Somebody else in the chat is called "bot" too: a short name is no
    longer clear, so the bot asks for its full handle instead of acting."""
    interaction = AllInteractions()
    client = _fake_client()
    fake_room = _fake_room("!room:example.org")
    _with_member(fake_room, other, display_name, invited=invited)
    room = Room.objects.create(room_id="!room:example.org")
    RoomMember.objects.create(room=room, user_id="@mod:example.org", power_level=50)

    event = _fake_event("$1", body, sender="@mod:example.org")
    asyncio.run(interaction.on_matrix_message(client, fake_room, event))

    reply = client.send_message.await_args.args[1]
    assert "mention me directly" in reply
    assert "@bot:example.org hello" in reply


def test_the_full_handle_still_works_if_the_name_is_shared() -> None:
    interaction = AllInteractions()
    client = _fake_client()
    fake_room = _fake_room("!room:example.org")
    _with_member(fake_room, "@bot:other.org")
    room = Room.objects.create(room_id="!room:example.org")
    RoomMember.objects.create(room=room, user_id="@mod:example.org", power_level=50)

    event = _fake_event("$1", "@bot:example.org: hello", sender="@mod:example.org")
    asyncio.run(interaction.on_matrix_message(client, fake_room, event))

    assert client.send_message.await_args.args[1] == "Hello!"


def test_a_message_to_the_other_member_is_left_alone() -> None:
    """Only something the bot would do is answered: a chat between humans
    that happens to start with the shared name is not."""
    interaction = AllInteractions()
    client = _fake_client()
    fake_room = _fake_room("!room:example.org")
    _with_member(fake_room, "@bot:other.org")

    event = _fake_event("$1", "bot: how are you today", sender="@mod:example.org")
    asyncio.run(interaction.on_matrix_message(client, fake_room, event))

    client.send_message.assert_not_awaited()


def test_a_shared_localpart_does_not_stop_the_display_name() -> None:
    """Only the clashing name is unclear, the others still address the bot."""
    interaction = AllInteractions()
    client = _fake_client()
    fake_room = _fake_room("!room:example.org", bot_display_name="Jitsi")
    _with_member(fake_room, "@bot:other.org")
    room = Room.objects.create(room_id="!room:example.org")
    RoomMember.objects.create(room=room, user_id="@mod:example.org", power_level=50)

    event = _fake_event("$1", "@Jitsi hello", sender="@mod:example.org")
    asyncio.run(interaction.on_matrix_message(client, fake_room, event))

    assert client.send_message.await_args.args[1] == "Hello!"


@pytest.mark.parametrize("body", ["@bot hello", "@bot: hello", "@bot, hello"])
def test_bot_replies_when_addressed_as_at_its_name(body) -> None:
    """``@jitsi-bot`` typed or copied as plain text - the way the
    documentation writes a command - is a mention, though it is neither
    the full user ID nor a mention picked from the client's list."""
    interaction = AllInteractions()
    client = _fake_client()  # its user ID is @bot:example.org
    fake_room = _fake_room("!room:example.org")
    room = Room.objects.create(room_id="!room:example.org")
    RoomMember.objects.create(room=room, user_id="@mod:example.org", power_level=50)

    event = _fake_event("$1", body, sender="@mod:example.org")
    asyncio.run(interaction.on_matrix_message(client, fake_room, event))

    assert client.send_message.await_args.args[1] == "Hello!"


def test_bot_does_not_reply_to_the_same_name_on_another_server() -> None:
    """``@bot:other.org`` is somebody else, not this bot."""
    interaction = AllInteractions()
    client = _fake_client()
    fake_room = _fake_room("!room:example.org")

    event = _fake_event("$1", "@bot:other.org: hello", sender="@anyone:example.org")
    asyncio.run(interaction.on_matrix_message(client, fake_room, event))

    client.send_message.assert_not_awaited()


def test_bot_replies_to_a_markdown_pill_mention() -> None:
    """Regression test for the actual reported outage: the sender's
    Matrix client rendered the mention as a Markdown link in the
    plain-text body - ``[jitsi-bot-test](https://matrix.to/#/@jitsi-
    bot-test:chat.pycal.org)`` - a shape neither the original
    shape-only check nor the display-name fix recognised at all, so
    the bot never replied to anything addressed this way.
    """
    interaction = AllInteractions()
    client = _fake_client()
    client.user_id = "@jitsi-bot-test:chat.pycal.org"
    fake_room = _fake_room("!room:example.org")

    room = Room.objects.create(room_id="!room:example.org")
    RoomMember.objects.create(room=room, user_id="@mod:example.org", power_level=50)

    event = _fake_event(
        "$1",
        "[jitsi-bot-test](https://matrix.to/#/@jitsi-bot-test:chat.pycal.org) hello",
        sender="@mod:example.org",
    )
    asyncio.run(interaction.on_matrix_message(client, fake_room, event))

    assert client.send_message.await_args.args[1] == "Hello!"


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
