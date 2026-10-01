"""Showing a speaker on a room's avatar while a conference is active."""

import asyncio
import io
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import nio
import pytest
from PIL import Image

from matrix_jitsi_bot.bot import MatrixJitsiBot
from matrix_jitsi_bot.db.models import (
    Account,
    JitsiRoom,
    Room,
    TrackedJitsiRoom,
)
from matrix_jitsi_bot.interactions.avatar import AvatarInteraction

_URL = "https://meet.example.org/Room"
_MXC = "mxc://example.org/original"


def _png(color) -> bytes:
    out = io.BytesIO()
    Image.new("RGBA", (64, 64), color).save(out, format="PNG")
    return out.getvalue()


@pytest.fixture
def setup():
    account = Account.objects.create(
        user_id="@bot:example.org", homeserver="https://example.org"
    )
    room = Room.objects.create(room_id="!room:example.org", account=account)
    jitsi_room = JitsiRoom.objects.create(url=_URL)
    TrackedJitsiRoom.objects.create(room=room, jitsi_room=jitsi_room, show_speaker=True)
    return room, jitsi_room


def _client(*, allowed=True, avatar_url=_MXC):
    client = AsyncMock()
    client.user_id = "@bot:example.org"
    matrix_room = MagicMock(spec=nio.MatrixRoom)
    matrix_room.power_levels = MagicMock()
    matrix_room.room_avatar_url = avatar_url
    matrix_room.power_levels.can_user_send_state.return_value = allowed
    client.rooms = {"!room:example.org": matrix_room}
    client.download.return_value = nio.DownloadResponse(
        body=_png("red"), content_type="image/png", filename=None
    )
    client.upload.return_value = (
        SimpleNamespace(content_uri="mxc://example.org/new"),
        None,
    )
    client.room_put_state.return_value = SimpleNamespace()
    return client


def _update(client):
    asyncio.run(MatrixJitsiBot().update_speaker_avatars(client))


def test_nothing_changes_while_the_conference_is_closed(setup) -> None:
    client = _client()
    _update(client)
    client.room_put_state.assert_not_awaited()


def test_avatar_is_cached_and_overlaid_when_active_then_restored(setup) -> None:
    room, jitsi_room = setup
    jitsi_room.is_open = True
    jitsi_room.save()
    client = _client()

    _update(client)

    room.refresh_from_db()
    assert room.speaker_shown
    assert bytes(room.original_avatar) == _png("red")
    client.room_put_state.assert_awaited_once_with(
        "!room:example.org",
        "m.room.avatar",
        {"url": "mxc://example.org/new"},
        state_key="",
    )

    _update(client)  # unchanged: nothing more happens
    assert client.room_put_state.await_count == 1

    jitsi_room.is_open = False
    jitsi_room.save()
    _update(client)

    assert client.room_put_state.await_count == 2
    assert client.upload.await_args.args[0].getvalue() == _png("red")
    room.refresh_from_db()
    assert not room.speaker_shown
    assert room.original_avatar is None


def test_a_room_without_avatar_gets_none_back(setup) -> None:
    room, jitsi_room = setup
    jitsi_room.is_open = True
    jitsi_room.save()
    client = _client(avatar_url=None)
    _update(client)
    client.download.assert_not_awaited()
    shown = Image.open(client.upload.await_args.args[0])
    assert shown.size == (256, 256)
    assert shown.getpixel((128, 128))[3] == 255  # the full speaker

    jitsi_room.is_open = False
    jitsi_room.save()
    _update(client)

    client.room_put_state.assert_awaited_with(
        "!room:example.org", "m.room.avatar", {}, state_key=""
    )
    room.refresh_from_db()
    assert not room.speaker_shown


def test_nothing_is_changed_without_permission(setup) -> None:
    _, jitsi_room = setup
    jitsi_room.is_open = True
    jitsi_room.save()
    client = _client(allowed=False)
    _update(client)
    client.room_put_state.assert_not_awaited()
    assert not Room.objects.get(room_id="!room:example.org").speaker_shown


def test_a_failed_change_is_not_cached(setup) -> None:
    _, jitsi_room = setup
    jitsi_room.is_open = True
    jitsi_room.save()
    client = _client()
    client.room_put_state.return_value = nio.RoomPutStateError("no")
    _update(client)
    room = Room.objects.get(room_id="!room:example.org")
    assert not room.speaker_shown
    assert room.original_avatar is None


def test_untracking_restores_the_avatar(setup) -> None:
    room, jitsi_room = setup
    jitsi_room.is_open = True
    jitsi_room.save()
    client = _client()
    _update(client)
    TrackedJitsiRoom.objects.all().delete()
    _update(client)
    room.refresh_from_db()
    assert not room.speaker_shown


def test_command_requires_moderator_and_avatar_permission(
    send_message, make_moderator
) -> None:
    conv = send_message(
        f"@bot: change avatar when {_URL} is active", sender="@mod:example.org"
    )
    result = AvatarInteraction().react_to_matrix_message(conv)
    assert "only room moderators" in result.text

    make_moderator(conv, "@mod:example.org")
    result = AvatarInteraction().react_to_matrix_message(conv)
    assert "not allowed to change this room's avatar" in result.text
    assert result.reaction == "❌"
    assert not TrackedJitsiRoom.objects.exists()


def test_command_tracks_and_can_be_undone(send_message, make_moderator) -> None:
    conv = send_message(
        f"@bot: change avatar when {_URL} is active", sender="@mod:example.org"
    )
    make_moderator(conv, "@mod:example.org")
    interaction = AvatarInteraction()
    interaction.can_set_avatar = True

    result = interaction.react_to_matrix_message(conv)

    assert result.reaction == "✅"
    assert TrackedJitsiRoom.objects.get().show_speaker

    conv = send_message(
        "@bot: don't change avatar when Room is active", sender="@mod:example.org"
    )
    interaction.react_to_matrix_message(conv)
    assert not TrackedJitsiRoom.objects.exists()


def _dispatch(bot_level: int):
    """Send the change-avatar command through the real
    ``on_matrix_message``, in a room where the bot has ``bot_level``.
    ``nio``'s own power levels decide whether it may change the avatar.
    """
    from datetime import UTC, datetime

    from matrix_jitsi_bot.db.models import RoomMember

    bot_id = "@bot:example.org"
    interaction = AvatarInteraction()
    client = MagicMock(user_id=bot_id)
    client.send_message = AsyncMock()
    client.add_reaction = AsyncMock()
    room = nio.MatrixRoom("!room:example.org", bot_id)
    # What a real room's power levels event usually says: changing state
    # takes 50. (nio assumes 0 for a room it has no such event for.)
    room.power_levels.defaults.state_default = 50
    room.power_levels.users[bot_id] = bot_level
    stored = Room.objects.create(room_id=room.room_id)
    RoomMember.objects.create(room=stored, user_id="@mod:example.org", power_level=50)
    event = MagicMock(
        sender="@mod:example.org",
        body=f"{bot_id}: change avatar when {_URL} is active",
        event_id="$show1",
        server_timestamp=int(datetime.now(tz=UTC).timestamp() * 1000),
        source={},
    )

    asyncio.run(interaction.on_matrix_message(client, room, event))

    return interaction, client


def test_bot_without_the_power_to_change_the_avatar_refuses() -> None:
    interaction, client = _dispatch(bot_level=0)

    reply = client.send_message.await_args.args[1]
    assert "I am not allowed to change this room's avatar" in reply
    assert not TrackedJitsiRoom.objects.exists()
    assert interaction.can_set_avatar is False


def test_bot_with_the_power_to_change_the_avatar_tracks_the_conference() -> None:
    interaction, client = _dispatch(bot_level=50)

    reply = client.send_message.await_args.args[1]
    assert reply.startswith(f"Now tracking {_URL}.")
    assert TrackedJitsiRoom.objects.get().show_speaker
    assert interaction.can_set_avatar is False  # reset after every message


def _leaving(setup, client):
    """The room shows the speaker, and is flagged to be left."""
    room, jitsi_room = setup
    jitsi_room.is_open = True
    jitsi_room.save()
    _update(client)
    room.refresh_from_db()
    assert room.speaker_shown
    room.should_leave = True
    room.save()
    client.reset_mock()
    asyncio.run(MatrixJitsiBot.leave_if_flagged(client, room.room_id))


def test_leaving_a_room_restores_its_avatar_first(setup) -> None:
    client = _client()

    _leaving(setup, client)

    names = [call[0] for call in client.mock_calls]
    assert names.index("upload") < names.index("room_put_state")
    assert names.index("room_put_state") < names.index("room_leave")
    assert client.upload.await_args.args[0].getvalue() == _png("red")
    assert not Room.objects.filter(room_id="!room:example.org").exists()


def test_leaving_a_room_leaves_even_if_the_avatar_cannot_be_restored(setup) -> None:
    client = _client()
    room, jitsi_room = setup
    jitsi_room.is_open = True
    jitsi_room.save()
    _update(client)  # shown
    room.should_leave = True
    room.save()
    client.reset_mock()
    client.room_put_state.return_value = nio.RoomPutStateError("no")

    asyncio.run(MatrixJitsiBot.leave_if_flagged(client, room.room_id))

    client.room_leave.assert_awaited_once_with("!room:example.org")
    assert not Room.objects.filter(room_id="!room:example.org").exists()


def test_pausing_restores_the_avatar_and_unpausing_shows_the_speaker_again(
    setup,
) -> None:
    room, jitsi_room = setup
    jitsi_room.is_open = True
    jitsi_room.save()
    client = _client()
    _update(client)
    room.refresh_from_db()
    assert room.speaker_shown

    room.paused = True
    room.save()
    _update(client)

    room.refresh_from_db()
    assert not room.speaker_shown  # restored while the conference is still open
    assert room.original_avatar is None
    assert client.upload.await_args.args[0].getvalue() == _png("red")
    assert client.room_put_state.await_count == 2

    room.paused = False
    room.save()
    _update(client)

    room.refresh_from_db()
    assert room.speaker_shown
    assert bytes(room.original_avatar) == _png("red")
    assert client.room_put_state.await_count == 3


def test_a_paused_room_gets_no_speaker() -> None:
    account = Account.objects.create(
        user_id="@bot:example.org", homeserver="https://example.org"
    )
    room = Room.objects.create(
        room_id="!room:example.org", account=account, paused=True
    )
    jitsi_room = JitsiRoom.objects.create(url=_URL, is_open=True)
    TrackedJitsiRoom.objects.create(room=room, jitsi_room=jitsi_room, show_speaker=True)
    client = _client()

    _update(client)

    client.room_put_state.assert_not_awaited()


def test_the_speaker_is_at_the_right_in_the_middle_of_a_chat_avatar(setup) -> None:
    """The chat has the full speaker at the right, in the middle of the
    height, 1/2 as wide - a space has it at the bottom right, see
    ``test_the_speaker_is_at_the_bottom_right_of_a_space_avatar``.
    """
    _, jitsi_room = setup
    jitsi_room.is_open = True
    jitsi_room.save()
    client = _client()  # its avatar is 64 x 64 pixels, all red

    _update(client)

    shown = Image.open(client.upload.await_args.args[0]).convert("RGBA")
    red = (255, 0, 0, 255)
    assert shown.size == (64, 64)
    assert shown.getpixel((48, 32)) != red  # the speaker: x 32..63, y 16..47
    assert shown.getpixel((48, 4)) == red  # above it
    assert shown.getpixel((48, 60)) == red  # below it
    assert shown.getpixel((4, 32)) == red  # left of it
