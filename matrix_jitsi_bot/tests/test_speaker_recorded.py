"""The speaker avatar replayed from recordings of the real thing.

:file:`fixtures/live_avatar.json` (a room without an avatar) and
:file:`fixtures/live_avatar_with_original.json` (a room with one) were
recorded by ``test_live_avatar.py`` (run with ``MJB_RECORD=1``) from a
real homeserver: the power levels of the room, and what the bot sent
and was answered while showing the speaker and putting the avatar back.
Here, the homeserver's answers are played back to the bot - no network.
"""

import asyncio
import io
import json
from unittest.mock import AsyncMock, MagicMock

import nio
import pytest
from PIL import Image

from matrix_jitsi_bot.bot import MatrixJitsiBot
from matrix_jitsi_bot.db.models import Account, JitsiRoom, Room, TrackedJitsiRoom
from matrix_jitsi_bot.tests.test_live_avatar import (
    FIXTURE,
    FIXTURE_WITH_AVATAR,
    preset_avatar,
)


def _load(path) -> dict:
    return json.loads(path.read_text())


def _power_levels(recording: dict) -> nio.PowerLevels:
    recorded = recording["power_levels"]
    return nio.PowerLevels(
        defaults=nio.events.room_events.DefaultLevels(**recorded["defaults"]),
        users=recorded["users"],
        events=recorded["events"],
    )


def _replaying_client(recording: dict, original: bytes | None):
    """A client answering like the recorded homeserver did. ``original``
    is the avatar the room had - the recording keeps only its size and
    hash, not the image.
    """
    client = AsyncMock()
    client.user_id = recording["user_id"]
    room = MagicMock(spec=nio.MatrixRoom)
    room.room_avatar_url = recording["avatar_url_before"]
    room.power_levels = _power_levels(recording)
    client.rooms = {recording["room_id"]: room}

    calls = recording["calls"]
    downloads = [c for c in calls if c["method"] == "download"]
    uploads = [c for c in calls if c["method"] == "upload"]
    puts = [c for c in calls if c["method"] == "room_put_state"]
    client.download = AsyncMock(
        side_effect=[
            nio.MemoryDownloadResponse(
                original, c["response"]["content_type"], c["response"]["filename"]
            )
            for c in downloads
        ]
    )
    client.upload = AsyncMock(
        side_effect=[
            (nio.UploadResponse(c["response"]["content_uri"]), None) for c in uploads
        ]
    )
    client.room_put_state = AsyncMock(
        side_effect=[
            nio.RoomPutStateResponse(
                c["response"]["event_id"], c["response"]["room_id"]
            )
            for c in puts
        ]
    )
    return client


def _setup(recording: dict):
    account = Account.objects.create(
        user_id=recording["user_id"], homeserver="https://example.org"
    )
    room = Room.objects.create(room_id=recording["room_id"], account=account)
    jitsi_room = JitsiRoom.objects.create(url="https://meet.example.org/Live")
    TrackedJitsiRoom.objects.create(room=room, jitsi_room=jitsi_room, show_speaker=True)
    return room, jitsi_room


@pytest.mark.parametrize("path", [FIXTURE, FIXTURE_WITH_AVATAR])
def test_the_recorded_account_may_change_the_avatar(path) -> None:
    recording = _load(path)
    levels = _power_levels(recording)
    assert recording["can_set_avatar"] is True
    assert levels.can_user_send_state(recording["user_id"], "m.room.avatar")
    assert not levels.can_user_send_state("@nobody:example.org", "m.room.avatar")


def _assert_same_conversation(recording: dict, client) -> None:
    """The bot made the same requests as in the recording, in order."""
    calls = recording["calls"]

    for sent, recorded in zip(
        client.download.await_args_list,
        [c for c in calls if c["method"] == "download"],
        strict=True,
    ):
        assert sent.kwargs == recorded["kwargs"]

    for sent, recorded in zip(
        client.upload.await_args_list,
        [c for c in calls if c["method"] == "upload"],
        strict=True,
    ):
        assert sent.kwargs["content_type"] == recorded["kwargs"]["content_type"]
        assert sent.kwargs["filename"] == recorded["kwargs"]["filename"]
        assert sent.kwargs["filesize"] == len(sent.args[0].getvalue())

    sent_states = [
        {"args": list(c.args[:2]), "content": c.args[2], "kwargs": dict(c.kwargs)}
        for c in client.room_put_state.await_args_list
    ]
    recorded_states = [
        {"args": c["args"], "content": c["content"], "kwargs": c["kwargs"]}
        for c in calls
        if c["method"] == "room_put_state"
    ]
    assert sent_states == recorded_states


def test_a_room_without_avatar_gets_the_full_speaker_and_none_back() -> None:
    recording = _load(FIXTURE)
    room, jitsi_room = _setup(recording)
    client = _replaying_client(recording, None)
    bot = MatrixJitsiBot()

    jitsi_room.is_open = True
    jitsi_room.save()
    asyncio.run(bot.update_speaker_avatars(client))
    room.refresh_from_db()
    assert room.speaker_shown
    assert room.original_avatar is None

    jitsi_room.is_open = False
    jitsi_room.save()
    asyncio.run(bot.update_speaker_avatars(client))
    room.refresh_from_db()
    assert not room.speaker_shown

    client.download.assert_not_awaited()
    _assert_same_conversation(recording, client)
    (upload,) = client.upload.await_args_list
    image = Image.open(io.BytesIO(upload.args[0].getvalue()))
    assert image.format == "PNG"
    assert image.size[0] == image.size[1]
    states = client.room_put_state.await_args_list
    assert states[0].args[2] == {
        "url": recording["calls"][0]["response"]["content_uri"]
    }
    assert states[1].args[2] == {}


def test_a_room_with_an_avatar_gets_the_speaker_on_it_and_the_avatar_back() -> None:
    recording = _load(FIXTURE_WITH_AVATAR)
    room, jitsi_room = _setup(recording)
    original = preset_avatar()
    client = _replaying_client(recording, original)
    bot = MatrixJitsiBot()

    jitsi_room.is_open = True
    jitsi_room.save()
    asyncio.run(bot.update_speaker_avatars(client))
    room.refresh_from_db()
    assert room.speaker_shown
    assert bytes(room.original_avatar) == original  # cached in the database
    assert room.original_avatar_type == "image/png"

    jitsi_room.is_open = False
    jitsi_room.save()
    asyncio.run(bot.update_speaker_avatars(client))
    room.refresh_from_db()
    assert not room.speaker_shown
    assert room.original_avatar is None  # removed from the database again

    _assert_same_conversation(recording, client)
    shown, restored = client.upload.await_args_list
    picture = Image.open(io.BytesIO(shown.args[0].getvalue())).convert("RGBA")
    assert picture.size == (120, 120)
    assert picture.getpixel((5, 115)) == (255, 0, 0, 255)  # the original
    assert picture.getpixel((60, 60)) == (0, 0, 255, 255)  # the original
    assert picture.getpixel((115, 5)) != (0, 0, 255, 255)  # the speaker
    assert restored.args[0].getvalue() == original  # put back unchanged
