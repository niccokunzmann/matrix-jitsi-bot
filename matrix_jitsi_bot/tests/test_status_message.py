"""The message that links the conferences of a chat and that the bot edits."""

import asyncio
from datetime import timedelta
from itertools import count
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import nio
import pytest
from django.utils import timezone

from matrix_jitsi_bot.bot import MatrixJitsiBot, _forget_deleted_status_message
from matrix_jitsi_bot.db.models import (
    Account,
    CommandReply,
    JitsiRoom,
    Room,
    StatusMessage,
    TrackedJitsiRoom,
)
from matrix_jitsi_bot.db.models.status_message import (
    conference_status_text,
    no_conference_text,
)
from matrix_jitsi_bot.interactions import AllInteractions
from matrix_jitsi_bot.interactions.status_message import StatusMessageInteraction

_BOT = "@bot:example.org"
_MOD = "@mod:example.org"
_CHAT = "!chat:example.org"
_A = "https://meet.example.org/A"
_B = "https://meet.example.org/B"
_COMMAND = "@bot: create conference status message"


def _conference(url, *, running=False) -> JitsiRoom:
    return JitsiRoom(url=url, is_open=running)


# -- what the message says ----------------------------------------------


@pytest.mark.no_database
@pytest.mark.parametrize(
    ("conferences", "text"),
    [
        ([], no_conference_text()),
        (
            [_conference(_A)],
            f"Click <{_A}> to start the Audio/Video conference.",
        ),
        (
            [_conference(_A), _conference(_B)],
            f"Click a link to start the Audio/Video conference:\n- <{_A}>\n- <{_B}>",
        ),
        (
            [_conference(_A, running=True)],
            f"🔊 Click <{_A}> to join the Audio/Video conference.",
        ),
        (
            [_conference(_A, running=True), _conference(_B, running=True)],
            f"🔊 Click a link to join the Audio/Video conferences:\n- <{_A}>\n- <{_B}>",
        ),
    ],
    ids=["none", "one-closed", "two-closed", "one-running", "two-running"],
)
def test_the_text_of_the_message(conferences, text) -> None:
    assert conference_status_text(conferences) == text


@pytest.mark.no_database
def test_only_the_running_conferences_are_listed() -> None:
    """Whoever clicks a conference that is not active would start it and
    wonder why nobody is there."""
    text = conference_status_text([_conference(_A), _conference(_B, running=True)])
    assert text == f"🔊 Click <{_B}> to join the Audio/Video conference."

    text = conference_status_text(
        [
            _conference(_A),
            _conference(_B, running=True),
            _conference(_A + "2", running=True),
        ]
    )
    assert text == (
        f"🔊 Click a link to join the Audio/Video conferences:\n- <{_B}>\n- <{_A}2>"
    )


# -- the command ---------------------------------------------------------


@pytest.fixture
def chat(send_message, make_moderator):
    """A `chat(body, sender)` function: a message in a chat of the bot
    account that tracks the conference ``_A``, where ``_MOD`` is a moderator.
    """
    account, _ = Account.objects.get_or_create(
        user_id=_BOT, defaults={"homeserver": "https://example.org"}
    )
    events = count(1)

    def _send(body: str = _COMMAND, sender: str = _MOD):
        conv = send_message(body, room_id=_CHAT, sender=sender)
        conv.room.account = account
        conv.room.save()
        make_moderator(conv, _MOD)
        return conv

    _send.events = events
    return _send


def _track(room_id=_CHAT, url=_A, *, running=False) -> JitsiRoom:
    room, _ = Room.objects.get_or_create(room_id=room_id)
    jitsi_room, _ = JitsiRoom.objects.get_or_create(url=url)
    jitsi_room.is_open = running
    jitsi_room.save()
    TrackedJitsiRoom.objects.get_or_create(
        room=room, jitsi_room=jitsi_room, defaults={"track_open": True}
    )
    return jitsi_room


def _client() -> AsyncMock:
    """A client that numbers the events it sends."""
    client = AsyncMock()
    client.user_id = _BOT
    numbers = count(1)

    async def _send(*_args, **_kwargs):
        return SimpleNamespace(event_id=f"$sent{next(numbers)}")

    client.send_message.side_effect = _send
    return client


def _run(conv, client):
    interaction = StatusMessageInteraction()
    interaction.matrix_client = client
    return interaction.react_to_matrix_message(conv)


def test_the_message_is_posted_as_a_reply_and_remembered(chat) -> None:
    _track()
    client = _client()

    result = _run(chat(), client)

    client.send_message.assert_awaited_once_with(
        _CHAT,
        f"Click <{_A}> to start the Audio/Video conference.",
        reply_to="$evt1",
    )
    message = StatusMessage.objects.get()
    assert (message.room.room_id, message.event_id) == (_CHAT, "$sent1")
    assert message.text == f"Click <{_A}> to start the Audio/Video conference."
    assert result.reaction == "✅"


def test_the_bot_answers_its_own_message_what_it_is_for(chat) -> None:
    _track()

    result = _run(chat(), _client())

    assert isinstance(result, CommandReply)
    assert result.reply_to_event_id == "$sent1"  # the status message, not the command
    assert result.text == (
        "✅ This message will be edited with the status of the conferences. "
        "Feel free to pin this message to the chat. "
        "Delete the message to stop this."
    )


def test_the_note_is_sent_as_a_reply_to_the_status_message(chat) -> None:
    _track()
    client = _client()
    result = _run(chat(), client)
    client.reset_mock()

    asyncio.run(result.send_message(client))

    assert client.send_message.await_args.kwargs["reply_to"] == "$sent1"
    client.add_reaction.assert_awaited_once_with(_CHAT, "$evt1", "✅")


def test_without_a_tracked_conference_there_is_nothing_to_list(chat) -> None:
    client = _client()

    result = _run(chat(), client)

    assert result.reaction == "❌"
    assert "No conference is tracked" in result.text
    assert "track status of" in result.text
    assert not StatusMessage.objects.exists()
    client.send_message.assert_not_awaited()


def test_only_moderators_create_it(chat) -> None:
    _track()
    client = _client()

    result = _run(chat(sender="@someone:example.org"), client)

    assert result.reaction == "❌"
    assert not StatusMessage.objects.exists()
    client.send_message.assert_not_awaited()


def test_a_chat_has_one_message_so_a_new_one_replaces_it(chat) -> None:
    _track()
    client = _client()
    _run(chat(), client)

    _run(chat(), client)

    message = StatusMessage.objects.get()  # still one
    assert message.event_id == "$sent2"
    client.delete_message.assert_awaited_once_with(_CHAT, "$sent1")


def test_the_note_says_that_the_previous_message_was_deleted(chat) -> None:
    _track()
    client = _client()
    first = _run(chat(), client)
    second = _run(chat(), client)

    assert "deleted" not in first.text
    assert second.text.endswith(" The previous status message was deleted.")
    assert second.reply_to_event_id == "$sent2"


def test_a_message_that_cannot_be_deleted_is_replaced_all_the_same(chat) -> None:
    _track()
    client = _client()
    _run(chat(), client)
    client.delete_message.side_effect = RuntimeError("not allowed")

    _run(chat(), client)

    assert StatusMessage.objects.get().event_id == "$sent2"


def test_other_ways_to_say_it(chat) -> None:
    _track()

    result = _run(chat("@bot: create a conference status message"), _client())

    assert result.reaction == "✅"


def test_the_command_is_listed_by_help_for_moderators(chat) -> None:
    conv = chat("@bot: help")

    result = AllInteractions().react_to_matrix_message(conv)

    assert "create conference status message" in result.text


def test_the_whole_conversation_in_the_right_order(
    send_message, make_moderator
) -> None:
    """The status message first, then the bot's note replying to it."""
    interaction = AllInteractions()
    account = Account.objects.create(user_id=_BOT, homeserver="https://example.org")
    room = Room.objects.create(room_id=_CHAT, account=account)
    make_moderator(SimpleNamespace(room=room), _MOD)
    _track()
    client = MagicMock(user_id=_BOT)
    numbers = count(1)

    async def _send(*_args, **_kwargs):
        return SimpleNamespace(event_id=f"$sent{next(numbers)}")

    client.send_message = AsyncMock(side_effect=_send)
    client.add_reaction = AsyncMock()
    matrix_room = MagicMock(room_id=_CHAT)
    matrix_room.user_name = MagicMock(return_value=None)
    matrix_room.users = {}
    matrix_room.invited_users = {}
    event = MagicMock(
        sender=_MOD,
        body=_COMMAND,
        event_id="$command",
        server_timestamp=0,
        source={},
    )

    asyncio.run(interaction.on_matrix_message(client, matrix_room, event))

    first, second = client.send_message.await_args_list
    assert first.args[1].startswith("Click <")
    assert first.kwargs["reply_to"] == "$command"
    assert second.args[1].startswith("✅ This message will be edited")
    assert second.kwargs["reply_to"] == "$sent1"


# -- keeping it up to date ------------------------------------------------


@pytest.fixture
def message():
    """A chat of the bot that tracks ``_A`` and shows its status message."""
    account, _ = Account.objects.get_or_create(
        user_id=_BOT, defaults={"homeserver": "https://example.org"}
    )
    room, _ = Room.objects.update_or_create(
        room_id=_CHAT, defaults={"account": account}
    )
    jitsi_room = _track()
    return StatusMessage.objects.create(
        room=room,
        event_id="$status",
        text=conference_status_text([jitsi_room]),
    )


def _update(client, bot=None):
    asyncio.run((bot or MatrixJitsiBot()).update_status_messages(client))


def test_nothing_is_edited_while_nothing_changed(message) -> None:
    client = _client()

    _update(client)

    client.edit_message.assert_not_awaited()


def test_the_message_says_join_while_the_conference_is_running(message) -> None:
    client = _client()
    jitsi_room = JitsiRoom.objects.get(url=_A)

    jitsi_room.is_open = True
    jitsi_room.save()
    _update(client)

    client.edit_message.assert_awaited_once_with(
        _CHAT, "$status", f"🔊 Click <{_A}> to join the Audio/Video conference."
    )
    message.refresh_from_db()
    assert message.text == f"🔊 Click <{_A}> to join the Audio/Video conference."

    jitsi_room.is_open = False
    jitsi_room.save()
    _update(client)

    assert client.edit_message.await_args.args[2] == (
        f"Click <{_A}> to start the Audio/Video conference."
    )
    assert client.edit_message.await_count == 2


def test_a_conference_that_is_added_is_listed(message) -> None:
    client = _client()

    _track(url=_B)
    _update(client)

    assert client.edit_message.await_args.args[2] == (
        f"Click a link to start the Audio/Video conference:\n- <{_A}>\n- <{_B}>"
    )


def test_only_the_running_one_of_two_is_linked_to_join(message) -> None:
    client = _client()
    _track(url=_B, running=True)

    _update(client)

    assert client.edit_message.await_args.args[2] == (
        f"🔊 Click <{_B}> to join the Audio/Video conference."
    )


def test_a_conference_that_is_not_tracked_anymore_leaves_the_message(message) -> None:
    client = _client()
    _track(url=_B)
    _update(client)

    TrackedJitsiRoom.objects.filter(jitsi_room__url=_B).delete()
    _update(client)

    assert client.edit_message.await_args.args[2] == (
        f"Click <{_A}> to start the Audio/Video conference."
    )


def test_a_message_with_no_conference_left_says_so(message) -> None:
    client = _client()

    TrackedJitsiRoom.objects.all().delete()
    _update(client)

    assert client.edit_message.await_args.args[2] == no_conference_text()


def test_a_paused_chat_keeps_its_message_until_it_is_unpaused(message) -> None:
    client = _client()
    JitsiRoom.objects.filter(url=_A).update(is_open=True)
    Room.objects.filter(room_id=_CHAT).update(paused=True)

    _update(client)
    client.edit_message.assert_not_awaited()

    Room.objects.filter(room_id=_CHAT).update(paused=False)
    _update(client)
    client.edit_message.assert_awaited_once()


def test_the_message_of_another_account_is_not_edited(message) -> None:
    other = _client()
    other.user_id = "@other:example.org"
    Account.objects.create(user_id=other.user_id, homeserver="https://example.org")
    JitsiRoom.objects.filter(url=_A).update(is_open=True)

    _update(other)

    other.edit_message.assert_not_awaited()


def test_a_message_that_cannot_be_edited_is_tried_again_later(message) -> None:
    client = _client()
    client.edit_message.side_effect = [RuntimeError("down"), None]
    bot = MatrixJitsiBot()
    JitsiRoom.objects.filter(url=_A).update(is_open=True)

    _update(client, bot)
    _update(client, bot)  # too soon
    assert client.edit_message.await_count == 1
    message.refresh_from_db()
    assert "start" in message.text  # still what was sent

    bot._status_retry_at.clear()  # the waiting time is over
    _update(client, bot)

    assert client.edit_message.await_count == 2
    message.refresh_from_db()
    assert "join" in message.text


def test_nothing_is_edited_before_the_first_sync(message) -> None:
    client = _client()
    client.next_batch = ""
    JitsiRoom.objects.filter(url=_A).update(is_open=True)

    _update(client)

    client.edit_message.assert_not_awaited()


def test_a_poll_edits_the_message(message) -> None:
    client = _client()
    # Not due for a check, which would ask the network.
    JitsiRoom.objects.filter(url=_A).update(
        is_open=True, next_check_at=timezone.now() + timedelta(days=1)
    )
    bot = MatrixJitsiBot()

    asyncio.run(bot.poll_jitsi_rooms_once(client))

    client.edit_message.assert_awaited_once()


# -- stopping it -----------------------------------------------------------


def test_deleting_the_message_stops_it(message) -> None:
    event = SimpleNamespace(redacts="$status")

    asyncio.run(_forget_deleted_status_message(MagicMock(spec=nio.MatrixRoom), event))

    assert not StatusMessage.objects.exists()


def test_deleting_another_message_does_not(message) -> None:
    event = SimpleNamespace(redacts="$other")

    asyncio.run(_forget_deleted_status_message(MagicMock(spec=nio.MatrixRoom), event))

    assert StatusMessage.objects.count() == 1


def test_resetting_the_chat_deletes_the_message(chat, message) -> None:
    client = _client()
    interaction = AllInteractions()
    interaction.matrix_client = client

    result = interaction.react_to_matrix_message(chat("@bot: don't track any"))

    assert result.reaction == "✅"
    assert not StatusMessage.objects.exists()
    client.delete_message.assert_awaited_once_with(_CHAT, "$status")


def test_resetting_a_chat_without_the_message_is_fine(chat) -> None:
    _track()
    interaction = AllInteractions()
    interaction.matrix_client = _client()

    result = interaction.react_to_matrix_message(chat("@bot: don't track any"))

    assert result.reaction == "✅"


def test_untracking_one_conference_keeps_the_message(chat, message) -> None:
    _track(url=_B)
    interaction = AllInteractions()
    interaction.matrix_client = _client()

    interaction.react_to_matrix_message(chat(f"@bot: don't track {_B}"))

    assert StatusMessage.objects.count() == 1


def test_leaving_the_chat_forgets_the_message(message) -> None:
    Room.objects.filter(room_id=_CHAT).delete()

    assert not StatusMessage.objects.exists()


def test_the_status_command_tells_about_the_message(chat, message) -> None:
    result = AllInteractions().react_to_matrix_message(chat("@bot: status"))

    assert "a message with the status of the conferences is kept up to date" in (
        result.text
    )


@pytest.mark.no_database
@pytest.mark.parametrize(
    ("version", "kind"), [("0.2.1.dev3", "latest"), ("0.2.0", "stable")]
)
def test_without_a_conference_the_message_links_how_to_set_one_up(
    monkeypatch, version, kind
) -> None:
    import importlib

    monkeypatch.setattr(
        importlib.import_module("matrix_jitsi_bot.version"), "__version__", version
    )

    assert conference_status_text([]) == (
        "No Jitsi conference is set up in this chat. Here is how to set one up: "
        f"<https://matrix-jitsi-bot.readthedocs.io/en/{kind}"
        "/using-a-bot/track-a-conference.html>"
    )
