import itertools
from datetime import UTC, datetime

import pytest

from matrix_jitsi_bot.interactions import BotInteraction, MessageReaction

_event_ids = itertools.count(1)


class Greeter(BotInteraction):
    @MessageReaction(r"hello (?P<name>\w+)")
    def react_to_greeting(self, name: str) -> str:
        return f"Hello, {name}!"

    @MessageReaction(r"remember (?P<note>.+)")
    def react_to_remember(self, note: str):
        from matrix_jitsi_bot.db.models import CommandReply

        return CommandReply(text=f"Noted: {note}")

    @MessageReaction(r"ignore me")
    def react_to_ignore(self):
        return None


def _send(
    body: str, room_id: str = "!room:example.org", sender: str = "@a:example.org"
):
    """Record `body` as if it had just arrived, and return its Conversation."""
    from matrix_jitsi_bot.db.models import Conversation, Message, Room

    room, _ = Room.objects.get_or_create(room_id=room_id)
    conv, _ = Conversation.objects.get_or_create(room=room)
    Message.objects.create(
        conversation=conv,
        sender=sender,
        event_id=f"$evt{next(_event_ids)}",
        body=body,
        server_timestamp=datetime.now(tz=UTC),
    )
    return conv


def test_plain_string_reply() -> None:
    conv = _send("hello world")
    greeter = Greeter()

    assert greeter.react_to_matrix_message(conv) == "Hello, world!"


def test_no_handler_matches() -> None:
    conv = _send("this matches nothing")
    greeter = Greeter()

    assert greeter.react_to_matrix_message(conv) is None


def test_handler_returning_none_falls_through() -> None:
    conv = _send("ignore me")
    greeter = Greeter()

    assert greeter.react_to_matrix_message(conv) is None


def test_whitespace_is_normalised_before_matching() -> None:
    conv = _send("hello   \n  world\t")
    greeter = Greeter()

    assert greeter.react_to_matrix_message(conv) == "Hello, world!"


def test_command_reply_is_persisted() -> None:
    from matrix_jitsi_bot.db.models import CommandReply

    conv = _send("remember buy milk", sender="@a:example.org")
    greeter = Greeter()

    result = greeter.react_to_matrix_message(conv)

    assert isinstance(result, CommandReply)
    assert result.pk is not None
    saved = CommandReply.objects.get(pk=result.pk)
    assert saved.message.body == "remember buy milk"
    assert saved.message.sender == "@a:example.org"
    assert saved.text == "Noted: buy milk"


def test_conversation_without_messages_raises() -> None:
    from matrix_jitsi_bot.db.models import Conversation, Room

    room = Room.objects.create(room_id="!empty:example.org")
    conv = Conversation.objects.create(room=room)
    greeter = Greeter()

    with pytest.raises(ValueError, match="no recorded messages"):
        greeter.react_to_matrix_message(conv)
