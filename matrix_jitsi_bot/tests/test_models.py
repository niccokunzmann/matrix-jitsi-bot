from matrix_jitsi_bot.db.models import Message, Room, RoomMember


def test_sanitized_body_collapses_whitespace() -> None:
    message = Message(body="hello   \n  world\t\tagain")
    assert message.sanitized_body == "hello world again"


def test_sanitized_body_strips_leading_trailing_whitespace() -> None:
    message = Message(body="  hi  ")
    assert message.sanitized_body == "hi"


def test_room_is_moderator_true_at_threshold() -> None:
    room = Room.objects.create(room_id="!room:example.org")
    RoomMember.objects.create(room=room, user_id="@mod:example.org", power_level=50)

    assert room.is_moderator("@mod:example.org") is True


def test_room_is_moderator_false_below_threshold() -> None:
    room = Room.objects.create(room_id="!room:example.org")
    RoomMember.objects.create(room=room, user_id="@user:example.org", power_level=0)

    assert room.is_moderator("@user:example.org") is False


def test_room_is_moderator_false_for_unknown_user() -> None:
    room = Room.objects.create(room_id="!room:example.org")

    assert room.is_moderator("@stranger:example.org") is False
