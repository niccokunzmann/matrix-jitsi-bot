import itertools
from datetime import UTC, datetime

from matrix_jitsi_bot.interactions import GreetingInteraction

_event_ids = itertools.count(1)


def _send(
    body: str, sender: str = "@a:example.org", room_id: str = "!room:example.org"
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


def test_hello() -> None:
    conv = _send("hello")

    result = GreetingInteraction().react_to_matrix_message(conv)

    assert result == "hello"


def test_mention_prefix_is_stripped() -> None:
    conv = _send("@bot:matrix.org: hello")

    result = GreetingInteraction().react_to_matrix_message(conv)

    assert result == "hello"


def test_unrelated_message_is_ignored() -> None:
    conv = _send("hello world")

    result = GreetingInteraction().react_to_matrix_message(conv)

    assert result is None
