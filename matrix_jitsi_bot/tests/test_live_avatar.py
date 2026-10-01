"""Changing a room's avatar on a real homeserver.

Runs only with ``MJB_LIVE=1`` - it changes the avatar of a real room
(and puts the original back), so it only runs on purpose. The test
account is taken from:

- the environment: ``MJB_TEST_USER_ID``, ``MJB_TEST_ACCESS_TOKEN``,
  ``MJB_TEST_HOMESERVER`` and optionally ``MJB_TEST_DEVICE_ID``, or else
- the first account in the bot's database ``MJB_TEST_DB`` (default:
  :file:`matrix-jitsi-bot.sqlite3` in the working directory), read only.

``MJB_TEST_ROOM_ID`` defaults to ``!vndFAZuZMWuRWHoMQW:chat.ccc-p.org``.
The account must be in the room, with the power to change its avatar.

With ``MJB_RECORD=1`` as well, what the bot and the homeserver say to each other
is written to :file:`fixtures/live_avatar.json` (for a room without an
avatar) and :file:`fixtures/live_avatar_with_original.json` (for one with
an avatar) - without credentials and image contents. See
``test_speaker_recorded.py``, which replays them.

The second test puts :py:func:`preset_avatar` on the room first, and the
room's avatar from before back at the end.
"""

import asyncio
import hashlib
import io
import json
import os
import sqlite3
from pathlib import Path

import pytest
from PIL import Image

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE = FIXTURES / "live_avatar.json"
FIXTURE_WITH_AVATAR = FIXTURES / "live_avatar_with_original.json"
_ROOM_ID = os.environ.get("MJB_TEST_ROOM_ID", "!vndFAZuZMWuRWHoMQW:chat.ccc-p.org")
_URL = "https://meet.example.org/LiveTest"


def _load_account() -> dict | None:
    """The test account: ``homeserver``, ``user_id``, ``access_token``,
    ``device_id`` - or ``None``.
    """
    if os.environ.get("MJB_TEST_USER_ID") and os.environ.get("MJB_TEST_ACCESS_TOKEN"):
        return {
            "homeserver": os.environ.get(
                "MJB_TEST_HOMESERVER", "https://chat.ccc-p.org"
            ),
            "user_id": os.environ["MJB_TEST_USER_ID"],
            "access_token": os.environ["MJB_TEST_ACCESS_TOKEN"],
            "device_id": os.environ.get("MJB_TEST_DEVICE_ID", ""),
        }
    path = Path(os.environ.get("MJB_TEST_DB", "matrix-jitsi-bot.sqlite3"))
    if not path.is_file():
        return None
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
        row = connection.execute(
            "select homeserver, user_id, access_token, device_id "
            "from matrix_jitsi_bot_account where access_token != '' order by id"
        ).fetchone()
    if row is None:
        return None
    return dict(
        zip(("homeserver", "user_id", "access_token", "device_id"), row, strict=False)
    )


_ACCOUNT = _load_account()

pytestmark = pytest.mark.skipif(
    os.environ.get("MJB_LIVE") != "1" or _ACCOUNT is None,
    reason="set MJB_LIVE=1 to change the avatar of a real room - with a test "
    "account: MJB_TEST_USER_ID and MJB_TEST_ACCESS_TOKEN, or an account "
    "with an access token in matrix-jitsi-bot.sqlite3",
)


def _describe_bytes(data: bytes) -> dict:
    return {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


class RecordingClient:
    """Passes everything to a real ``nio`` client, and records what the
    bot sends and what the homeserver answers - see :py:data:`FIXTURE`.
    """

    def __init__(self, client) -> None:
        self._client = client
        self.calls: list[dict] = []

    def __getattr__(self, name):
        return getattr(self._client, name)

    @staticmethod
    def _response(response) -> dict:
        data = {"type": type(response).__name__}
        for field in (
            "content_uri",
            "content_type",
            "filename",
            "event_id",
            "room_id",
            "status_code",
            "message",
        ):
            if hasattr(response, field):
                data[field] = getattr(response, field)
        if hasattr(response, "body"):
            data["body"] = _describe_bytes(response.body)
        return data

    async def download(self, **kwargs):
        response = await self._client.download(**kwargs)
        self.calls.append(
            {
                "method": "download",
                "kwargs": kwargs,
                "response": self._response(response),
            }
        )
        return response

    async def upload(self, data_provider, **kwargs):
        content = data_provider.read()
        data_provider.seek(0)
        response, keys = await self._client.upload(io.BytesIO(content), **kwargs)
        self.calls.append(
            {
                "method": "upload",
                "kwargs": kwargs,
                "data": _describe_bytes(content),
                "response": self._response(response),
            }
        )
        return response, keys

    async def room_put_state(self, room_id, event_type, content, **kwargs):
        response = await self._client.room_put_state(
            room_id, event_type, content, **kwargs
        )
        self.calls.append(
            {
                "method": "room_put_state",
                "args": [room_id, event_type],
                "content": content,
                "kwargs": kwargs,
                "response": self._response(response),
            }
        )
        return response


def _power_levels(room) -> dict:
    levels = room.power_levels
    return {
        "users": dict(levels.users),
        "events": dict(levels.events),
        "defaults": {
            "ban": levels.defaults.ban,
            "invite": levels.defaults.invite,
            "kick": levels.defaults.kick,
            "redact": levels.defaults.redact,
            "state_default": levels.defaults.state_default,
            "events_default": levels.defaults.events_default,
            "users_default": levels.defaults.users_default,
        },
    }


def preset_avatar() -> bytes:
    """A small avatar to put on the room: blue, with a red square at the
    bottom left, so it shows what is drawn over it and what is not.
    """
    image = Image.new("RGBA", (120, 120), (0, 0, 255, 255))
    image.paste((255, 0, 0, 255), (0, 90, 30, 120))
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


async def _avatar(client) -> bytes | None:
    url = client._client.rooms[_ROOM_ID].room_avatar_url
    if not url:
        return None
    return (await client._client.download(mxc=url)).body


async def _sync_until_avatar_is(client, url: str | None) -> None:
    """Sync until the room's avatar is ``url`` - one sync may return
    before the homeserver passes on the change.
    """
    for _ in range(10):
        await client.sync(timeout=3000)
        if client.rooms[_ROOM_ID].room_avatar_url == url:
            return
    pytest.fail(f"The avatar of {_ROOM_ID} did not become {url}")


def _last_avatar_set(client) -> str | None:
    """The avatar URL the bot set last, ``None`` if it removed it."""
    puts = [c for c in client.calls if c["method"] == "room_put_state"]
    return puts[-1]["content"].get("url")


async def _set_avatar(client, image: bytes | None) -> None:
    """Put ``image`` on the room as its avatar (``None``: none), not
    recorded - this is the test's setup, not the bot's work.
    """
    import nio

    content = {}
    if image is not None:
        upload, _ = await client._client.upload(
            io.BytesIO(image), content_type="image/png", filename="test-avatar"
        )
        assert isinstance(upload, nio.UploadResponse), upload
        content = {"url": upload.content_uri}
    response = await client._client.room_put_state(
        _ROOM_ID, "m.room.avatar", content, state_key=""
    )
    assert isinstance(response, nio.RoomPutStateResponse), response
    await _sync_until_avatar_is(client, content.get("url"))


async def _scenario(
    client: RecordingClient, *, preset: bytes | None, fixture: Path
) -> None:

    await client.sync(timeout=10000, full_state=True)
    assert client.rooms[_ROOM_ID].power_levels.can_user_send_state(
        client.user_id, "m.room.avatar"
    ), f"{client.user_id} may not change the avatar of {_ROOM_ID}"
    before_test = await _avatar(client)
    try:
        if preset is not None:
            await _set_avatar(client, preset)
        await _show_and_restore(client, fixture=fixture, preset=preset)
    finally:
        # The room is left as it was found.
        if await _avatar(client) != before_test:
            await _set_avatar(client, before_test)


async def _show_and_restore(
    client: RecordingClient, *, preset: bytes | None, fixture: Path
) -> None:
    from asgiref.sync import sync_to_async

    from matrix_jitsi_bot.bot import MatrixJitsiBot
    from matrix_jitsi_bot.db.models import Account, JitsiRoom, Room, TrackedJitsiRoom

    matrix_room = client.rooms[_ROOM_ID]
    original = await _avatar(client)
    if preset is not None:
        assert original == preset
    recording = {
        "room_id": _ROOM_ID,
        "user_id": client.user_id,
        "power_levels": _power_levels(matrix_room),
        "avatar_url_before": matrix_room.room_avatar_url,
        "can_set_avatar": matrix_room.power_levels.can_user_send_state(
            client.user_id, "m.room.avatar"
        ),
    }
    client.calls.clear()  # looking at the avatar is not part of the bot's work

    def _setup():
        account = Account.objects.create(
            user_id=client.user_id, homeserver=_ACCOUNT["homeserver"]
        )
        room = Room.objects.create(room_id=_ROOM_ID, account=account)
        jitsi_room = JitsiRoom.objects.create(url=_URL, is_open=True)
        TrackedJitsiRoom.objects.create(
            room=room, jitsi_room=jitsi_room, show_speaker=True
        )
        return room, jitsi_room

    room, jitsi_room = await sync_to_async(_setup)()
    bot = MatrixJitsiBot()
    try:
        await bot.update_speaker_avatars(client)
        await _sync_until_avatar_is(client, _last_avatar_set(client))
        await sync_to_async(room.refresh_from_db)()
        assert room.speaker_shown
        recording["avatar_url_shown"] = client.rooms[_ROOM_ID].room_avatar_url
        if preset is not None:
            assert bytes(room.original_avatar) == preset  # cached
        shown = await _avatar(client)
        assert shown is not None
        assert shown.startswith(b"\x89PNG")
        assert shown != original
        if preset is not None:  # the speaker is drawn over what was there
            picture = Image.open(io.BytesIO(shown)).convert("RGBA")
            assert picture.size == (120, 120)
            assert picture.getpixel((5, 115)) == (255, 0, 0, 255)  # kept
            assert picture.getpixel((60, 60)) == (0, 0, 255, 255)  # kept
            assert picture.getpixel((115, 5)) != (0, 0, 255, 255)  # speaker
        recording["shown"] = _describe_bytes(shown)
    finally:
        jitsi_room.is_open = False
        await sync_to_async(jitsi_room.save)()
        await bot.update_speaker_avatars(client)
        await _sync_until_avatar_is(client, _last_avatar_set(client))

    await sync_to_async(room.refresh_from_db)()
    assert not room.speaker_shown
    assert room.original_avatar is None  # un-cached
    assert await _avatar(client) == original  # restored
    recording["original"] = None if original is None else _describe_bytes(original)
    # What the test itself looks at goes around the recording client.
    recording["calls"] = list(client.calls)
    if os.environ.get("MJB_RECORD") == "1":
        text = json.dumps(recording, indent=2, sort_keys=True) + "\n"
        await asyncio.to_thread(fixture.write_text, text)


async def _run(*, preset: bytes | None, fixture: Path) -> None:
    import nio

    real = nio.AsyncClient(_ACCOUNT["homeserver"], _ACCOUNT["user_id"])
    real.restore_login(
        _ACCOUNT["user_id"],
        _ACCOUNT["device_id"] or "matrix-jitsi-bot-test",
        _ACCOUNT["access_token"],
    )
    try:
        await _scenario(RecordingClient(real), preset=preset, fixture=fixture)
    finally:
        await real.close()


def test_the_account_can_show_the_speaker_in_the_room_and_restore_the_avatar() -> None:
    asyncio.run(_run(preset=None, fixture=FIXTURE))


def test_the_speaker_is_drawn_over_the_avatar_of_the_room_and_it_is_restored() -> None:
    asyncio.run(_run(preset=preset_avatar(), fixture=FIXTURE_WITH_AVATAR))
