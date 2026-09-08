import itertools
from datetime import UTC, datetime

from matrix_jitsi_bot.interactions import ConfigurationInteraction

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


def test_list_languages() -> None:
    conv = _send("list languages")

    result = ConfigurationInteraction().react_to_matrix_message(conv)

    assert result == "en"


def test_set_language_rejects_non_moderator() -> None:
    conv = _send("set language to de", sender="@user:example.org")

    result = ConfigurationInteraction().react_to_matrix_message(conv)

    assert "only room moderators" in result
    assert conv.room.language == "en"


def test_set_language_accepts_moderator() -> None:
    from matrix_jitsi_bot.db.models import RoomMember

    conv = _send("set language to en", sender="@mod:example.org")
    RoomMember.objects.create(
        room=conv.room, user_id="@mod:example.org", power_level=50
    )

    result = ConfigurationInteraction().react_to_matrix_message(conv)

    assert result == "Language set to en."
    conv.room.refresh_from_db()
    assert conv.room.language == "en"


def test_set_language_rejects_unsupported_language() -> None:
    from matrix_jitsi_bot.db.models import RoomMember

    conv = _send("set language to klingon", sender="@mod:example.org")
    RoomMember.objects.create(
        room=conv.room, user_id="@mod:example.org", power_level=100
    )

    result = ConfigurationInteraction().react_to_matrix_message(conv)

    assert "don't speak" in result


def test_mention_prefix_is_stripped() -> None:
    conv = _send("@bot:matrix.org: list languages")

    result = ConfigurationInteraction().react_to_matrix_message(conv)

    assert result == "en"
