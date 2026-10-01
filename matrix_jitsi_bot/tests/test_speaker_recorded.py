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
from matrix_jitsi_bot.db.models import (
    Account,
    JitsiRoom,
    Room,
    Space,
    TrackedJitsiRoom,
)
from matrix_jitsi_bot.tests.test_live_avatar import (
    FIXTURE,
    FIXTURE_SPACE,
    FIXTURE_SPACE_NO_RIGHTS,
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
@pytest.mark.no_database
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
    assert picture.getpixel((20, 60)) == (0, 0, 255, 255)  # the original
    assert picture.getpixel((115, 5)) == (0, 0, 255, 255)  # kept: above the speaker
    assert picture.getpixel((90, 60)) != (
        0,
        0,
        255,
        255,
    )  # the speaker: right, in the middle
    assert restored.args[0].getvalue() == original  # put back unchanged


@pytest.mark.parametrize(
    "path", [FIXTURE_SPACE, FIXTURE_SPACE_NO_RIGHTS], ids=["not-listed", "no-rights"]
)
def test_a_space_as_recorded(path, send_message, make_moderator) -> None:
    """The recording of a real space - with its real power levels - and
    what the bot said and did: for a space that does not list the chat,
    the bot joined it, looked at it, said so and left again; for one that
    does not give it the power, it said so and stayed.
    """
    from matrix_jitsi_bot.interactions.avatar import AvatarInteraction
    from matrix_jitsi_bot.tests.test_live_avatar import _SENDER

    recording = _load(path)
    calls = recording["calls"]
    answers = {
        "join": lambda c: nio.JoinResponse(c["response"]["room_id"]),
        "room_get_state": lambda c: nio.RoomGetStateResponse(
            c["response"]["events"], c["response"]["room_id"]
        ),
        "room_leave": lambda _call: nio.RoomLeaveResponse(),
    }
    client = AsyncMock()
    client.user_id = recording["user_id"]
    # Without a join, the bot was in the space already.
    joins = [c for c in calls if c["method"] == "join"]
    in_space = MagicMock(canonical_alias=recording["space"])
    client.rooms = {} if joins else {recording["space_id"]: in_space}
    for method, answer in answers.items():
        matching = [c for c in calls if c["method"] == method]
        if matching:
            getattr(client, method).return_value = answer(matching[0])
    conv = send_message(
        f"@bot: change avatar of {recording['space']} when "
        "https://meet.example.org/LiveTest is active",
        room_id=recording["room_id"],
        sender=_SENDER,
    )
    make_moderator(conv, _SENDER)
    interaction = AvatarInteraction()
    interaction.matrix_client = client

    reply = interaction.react_to_matrix_message(conv)

    assert {"text": reply.text, "reaction": reply.reaction} == recording["reply"]
    for method in answers:
        sent = [c["args"] for c in calls if c["method"] == method]
        awaited = [c.args for c in getattr(client, method).await_args_list]
        assert awaited == [tuple(args) for args in sent], method
    assert not Space.objects.exists()
    assert not TrackedJitsiRoom.objects.exists()


def _space_power_levels(events: list[dict]) -> nio.PowerLevels:
    """The power levels of the recorded space, as ``nio`` holds them."""
    content = next(e["content"] for e in events if e["type"] == "m.room.power_levels")
    return nio.PowerLevels(
        defaults=nio.events.room_events.DefaultLevels(
            ban=content.get("ban", 50),
            invite=content.get("invite", 0),
            kick=content.get("kick", 50),
            redact=content.get("redact", 50),
            state_default=content.get("state_default", 50),
            events_default=content.get("events_default", 0),
            users_default=content.get("users_default", 0),
        ),
        users=content.get("users", {}),
        events=content.get("events", {}),
    )


def test_the_avatar_of_a_space_is_changed_and_restored_as_recorded(
    send_message, make_moderator
) -> None:
    """The whole conversation of the live test with a real space: it
    lists the chat and gives the bot the power. The command is accepted,
    the avatar of the space is downloaded, the same picture is set while
    the conference is open, and the original avatar is put back before
    the bot leaves the space - all without a server.
    """
    import asyncio

    from matrix_jitsi_bot.bot import MatrixJitsiBot
    from matrix_jitsi_bot.icon.merge import SamePicture
    from matrix_jitsi_bot.interactions.avatar import AvatarInteraction
    from matrix_jitsi_bot.tests.test_live_avatar import (
        _SENDER,
        FIXTURE_SPACE_CHANGE,
    )

    recording = _load(FIXTURE_SPACE_CHANGE)
    calls = recording["calls"]
    by_method = {
        m: [c for c in calls if c["method"] == m]
        for m in (
            "room_get_state",
            "download",
            "upload",
            "room_put_state",
            "room_leave",
        )
    }
    state = by_method["room_get_state"][0]["response"]
    original = io.BytesIO()
    Image.new("RGB", (40, 40), "teal").save(
        original, format="JPEG"
    )  # its size is not recorded
    original = original.getvalue()
    original_type = by_method["download"][0]["response"]["content_type"]
    recorded_avatar = next(
        e["content"]["url"] for e in state["events"] if e["type"] == "m.room.avatar"
    )
    assert recorded_avatar == by_method["download"][0]["kwargs"]["mxc"]

    # The bot, in the space already, as the real client saw it.
    space = MagicMock(spec=nio.MatrixRoom)
    space.canonical_alias = recording["space"]
    client = AsyncMock()
    client.user_id = recording["user_id"]
    client.rooms = {recording["space_id"]: space}
    client.room_get_state.return_value = nio.RoomGetStateResponse(
        state["events"], state["room_id"]
    )
    client.download.return_value = nio.MemoryDownloadResponse(
        original, original_type, None
    )
    client.upload.side_effect = [
        (nio.UploadResponse(c["response"]["content_uri"]), None)
        for c in by_method["upload"]
    ]
    client.room_put_state.side_effect = [
        nio.RoomPutStateResponse(c["response"]["event_id"], c["response"]["room_id"])
        for c in by_method["room_put_state"]
    ]
    client.room_leave.return_value = nio.RoomLeaveResponse()

    Account.objects.create(
        user_id=recording["user_id"], homeserver="https://example.org"
    )
    # The command of a moderator of the chat.
    conv = send_message(
        f"@bot: change avatar of {recording['space']} when "
        "https://meet.example.org/LiveTest is active",
        room_id=recording["room_id"],
        sender=_SENDER,
    )
    make_moderator(conv, _SENDER)
    interaction = AvatarInteraction()
    interaction.matrix_client = client
    reply = interaction.react_to_matrix_message(conv)
    assert {"text": reply.text, "reaction": reply.reaction} == recording["reply"]

    # The conference opens, and closes again.
    jitsi_room = JitsiRoom.objects.get(url="https://meet.example.org/LiveTest")
    bot = MatrixJitsiBot()
    bot.merger_with_avatar = bot.merger_without_avatar = SamePicture()
    bot.merger_space_with_avatar = SamePicture()
    jitsi_room.is_open = True
    jitsi_room.save()
    asyncio.run(bot.update_speaker_avatars(client))
    shown = Space.objects.get()
    assert shown.speaker_shown
    assert bytes(shown.original_avatar) == original  # cached
    jitsi_room.is_open = False
    jitsi_room.save()
    TrackedJitsiRoom.objects.all().delete()
    asyncio.run(bot.update_speaker_avatars(client))

    # What was said to the homeserver, in the order of the recording.
    # The space is asked about each time: to set it up, to show, to restore.
    assert [c.args for c in client.room_get_state.await_args_list] == [
        tuple(c["args"]) for c in by_method["room_get_state"]
    ]
    assert client.download.await_args.kwargs == by_method["download"][0]["kwargs"]
    shown_upload, restored_upload = client.upload.await_args_list
    recorded_shown, recorded_restored = by_method["upload"]
    for sent, recorded in (
        (shown_upload, recorded_shown),
        (restored_upload, recorded_restored),
    ):
        assert sent.kwargs["content_type"] == recorded["kwargs"]["content_type"]
        assert sent.kwargs["filename"] == recorded["kwargs"]["filename"]
        assert sent.kwargs["filesize"] == len(sent.args[0].getvalue())
    assert restored_upload.args[0].getvalue() == original  # put back unchanged
    assert [
        {"args": list(c.args[:2]), "content": c.args[2], "kwargs": dict(c.kwargs)}
        for c in client.room_put_state.await_args_list
    ] == [
        {"args": c["args"], "content": c["content"], "kwargs": c["kwargs"]}
        for c in by_method["room_put_state"]
    ]
    # Nobody uses the space anymore: the bot leaves it.
    client.room_leave.assert_awaited_once_with(*by_method["room_leave"][0]["args"])
    assert not Space.objects.exists()
    asked = ("room_get_state", "download", "upload", "room_put_state", "room_leave")
    assert [c[0] for c in client.mock_calls if c[0] in asked] == [
        c["method"] for c in calls
    ]
