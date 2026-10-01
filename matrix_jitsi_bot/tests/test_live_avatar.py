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
They do not run while a bot runs as the same account on this machine.

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
import time
from pathlib import Path

import pytest
from PIL import Image

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE = FIXTURES / "live_avatar.json"
FIXTURE_WITH_AVATAR = FIXTURES / "live_avatar_with_original.json"
FIXTURE_SPACE = FIXTURES / "live_space_avatar.json"
FIXTURE_SPACE_NO_RIGHTS = FIXTURES / "live_space_no_rights.json"
FIXTURE_SPACE_CHANGE = FIXTURES / "live_space_change.json"
_SPACE_ALIAS = os.environ.get("MJB_TEST_SPACE", "#pycal:chat.pycal.org")
_SENDER = os.environ.get("MJB_TEST_SENDER", "@niccokunzmann:chat.ccc-p.org")
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


@pytest.fixture(autouse=True)
def _no_bot_runs_as_this_account():
    """These tests join, leave and change rooms of the account. A bot that
    runs as the same account at the same time would see that - and, for
    example, forget what it was asked for. The bot's own lock tells.
    """
    from matrix_jitsi_bot.db.models.process import (
        AlreadyRunning,
        RunLock,
        account_lock_path,
    )

    lock = RunLock(account_lock_path(_ACCOUNT["user_id"]))
    try:
        lock.acquire()
    except AlreadyRunning:
        pytest.skip(f"a bot is running as {_ACCOUNT['user_id']} - stop it first")
    yield
    lock.release()


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


def _record_methods(cls):
    """Add what a space needs to ``RecordingClient``."""

    async def join(self, room_id, *args, **kwargs):
        response = await self._client.join(room_id, *args, **kwargs)
        self.calls.append(
            {
                "method": "join",
                "args": [room_id],
                "response": self._response(response),
            }
        )
        return response

    async def room_get_state(self, room_id):
        response = await self._client.room_get_state(room_id)
        recorded = self._response(response)
        if hasattr(response, "events"):
            recorded["events"] = _space_events(response.events)
        self.calls.append(
            {"method": "room_get_state", "args": [room_id], "response": recorded}
        )
        return response

    async def room_leave(self, room_id, *args, **kwargs):
        response = await self._client.room_leave(room_id, *args, **kwargs)
        self.calls.append(
            {
                "method": "room_leave",
                "args": [room_id],
                "response": self._response(response),
            }
        )
        return response

    cls.join = join
    cls.room_get_state = room_get_state
    cls.room_leave = room_leave
    return cls


def _space_events(events: list[dict]) -> list[dict]:
    """What the bot looks at of a space's state - the type, the power
    levels, its avatar and whether the chat is listed - without the
    rest of it.
    """
    keep = []
    for event in events:
        if event.get("type") in ("m.room.create", "m.room.power_levels"):
            content = event["content"]
            head = _event_head(event)
            if event["type"] == "m.room.create":
                content = {
                    key: content[key]
                    for key in ("type", "room_version", "additional_creators")
                    if key in content
                }
                head["sender"] = event.get("sender")
            keep.append({**head, "content": content})
        elif (
            event.get("type") == "m.room.avatar" and event.get("state_key") == ""
        ) or (
            event.get("type") == "m.space.child"
            and event.get("state_key") == _ROOM_ID
            and event.get("content", {}).get("via")
        ):
            keep.append({**_event_head(event), "content": event["content"]})
    return keep


def _event_head(event: dict) -> dict:
    return {"type": event["type"], "state_key": event["state_key"]}


RecordingClient = _record_methods(RecordingClient)


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
            assert picture.getpixel((20, 60)) == (0, 0, 255, 255)  # kept
            assert picture.getpixel((115, 5)) == (
                0,
                0,
                255,
                255,
            )  # kept: above the speaker
            assert picture.getpixel((90, 60)) != (
                0,
                0,
                255,
                255,
            )  # the speaker: right, in the middle
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


def _chat_message(account, sender: str, body: str):
    """The chat the bot is in, a moderator in it, and ``sender``'s message."""
    from datetime import UTC, datetime

    from matrix_jitsi_bot.db.models import (
        Conversation,
        JitsiRoom,
        Message,
        Room,
        RoomMember,
    )

    room = Room.objects.create(room_id=_ROOM_ID, account=account)
    RoomMember.objects.create(room=room, user_id=sender, power_level=50)
    JitsiRoom.objects.create(url=_URL, is_open=False)
    conversation = Conversation.objects.create(room=room)
    Message.objects.create(
        conversation=conversation,
        sender=sender,
        event_id="$live-space-1",
        body=body,
        server_timestamp=datetime.now(tz=UTC),
    )
    return conversation


async def _space_scenario(client: RecordingClient) -> None:
    """Ask for the avatar of a real space to change. What happens
    depends on the space: whether it lists the chat, and what the
    sender and the bot may do in it. If the avatar is changed, it is
    changed to the same picture. The account is in the space after
    the test if it was before, and not if it was not.
    """
    import nio
    from asgiref.sync import sync_to_async

    from matrix_jitsi_bot.db.models import Account, Space
    from matrix_jitsi_bot.interactions.avatar import AvatarInteraction

    real = client._client
    await client.sync(timeout=10000, full_state=True)
    resolved = await real.room_resolve_alias(_SPACE_ALIAS)
    assert isinstance(resolved, nio.RoomResolveAliasResponse), resolved
    space_id = resolved.room_id
    was_member = space_id in (await real.joined_rooms()).rooms
    account = await sync_to_async(Account.objects.create)(
        user_id=client.user_id, homeserver=_ACCOUNT["homeserver"]
    )
    conversation = await sync_to_async(_chat_message)(
        account,
        _SENDER,
        f"{client.user_id}: change avatar of {_SPACE_ALIAS} when {_URL} is active",
    )
    interaction = AvatarInteraction()
    interaction.matrix_client = client
    recording = {
        "room_id": _ROOM_ID,
        "user_id": client.user_id,
        "space": _SPACE_ALIAS,
        "space_id": space_id,
        "was_member": was_member,
    }

    try:
        reply = await sync_to_async(interaction.react_to_matrix_message)(conversation)
        recording["reply"] = {"text": reply.text, "reaction": reply.reaction}
        leaves = [c["args"] for c in client.calls if c["method"] == "room_leave"]
        if reply.reaction == "✅":
            await _change_and_restore(client, space_id, recording)
        elif "does not list this chat" in reply.text:
            assert leaves == [[space_id]], reply.text  # it leaves a space that does not
            assert not await sync_to_async(Space.objects.exists)()
        else:
            assert leaves == [], reply.text  # the others it stays in
            assert not await sync_to_async(Space.objects.exists)()
    finally:
        left = any(
            c["method"] == "room_leave" and c["args"] == [space_id]
            for c in client.calls
        )
        recording["calls"] = list(client.calls)
        if was_member and left:
            await real.join(_SPACE_ALIAS)
        elif not was_member and not left:
            await real.room_leave(space_id)
        if os.environ.get("MJB_RECORD") == "1":
            text = json.dumps(recording, indent=2, sort_keys=True) + "\n"
            await asyncio.to_thread(_space_fixture().write_text, text)


def _space_fixture() -> Path:
    """Where the conversation with the space is recorded."""
    return FIXTURES / os.environ.get("MJB_TEST_FIXTURE", FIXTURE_SPACE.name)


async def _change_and_restore(client, space_id: str, recording: dict) -> None:
    """The space lists the chat, and may be changed: the speaker is
    set - as the same picture - and the original put back.
    """
    from asgiref.sync import sync_to_async

    from matrix_jitsi_bot.bot import MatrixJitsiBot
    from matrix_jitsi_bot.db.models import JitsiRoom, Space, TrackedJitsiRoom
    from matrix_jitsi_bot.icon.merge import SamePicture

    await client.sync(timeout=10000)
    url = client.rooms[space_id].room_avatar_url
    original = (await client._client.download(mxc=url)).body if url else None
    jitsi_room = await sync_to_async(JitsiRoom.objects.get)(url=_URL)
    bot = MatrixJitsiBot()
    bot.merger_with_avatar = bot.merger_without_avatar = SamePicture()
    bot.merger_space_with_avatar = SamePicture()
    jitsi_room.is_open = True
    await sync_to_async(jitsi_room.save)()
    try:
        await bot.update_speaker_avatars(client)
        space = await sync_to_async(Space.objects.get)(room_id=space_id)
        assert space.speaker_shown
        await sync_to_async(space.refresh_from_db)()
        recording["original"] = None if original is None else _describe_bytes(original)
    finally:
        jitsi_room.is_open = False
        await sync_to_async(jitsi_room.save)()
        await bot.update_speaker_avatars(client)
        await sync_to_async(TrackedJitsiRoom.objects.all().delete)()
        await bot.update_speaker_avatars(client)  # leaves the unused space
    if original is not None:
        await client.sync(timeout=10000)
        assert (
            await client._client.download(mxc=client.rooms[space_id].room_avatar_url)
        ).body == original


def test_the_bot_joins_a_space_and_sets_up_or_reports_and_leaves_again() -> None:
    import nio

    async def _go():
        real = nio.AsyncClient(_ACCOUNT["homeserver"], _ACCOUNT["user_id"])
        real.restore_login(
            _ACCOUNT["user_id"],
            _ACCOUNT["device_id"] or "matrix-jitsi-bot-test",
            _ACCOUNT["access_token"],
        )
        try:
            await _space_scenario(RecordingClient(real))
        finally:
            await real.close()

    asyncio.run(_go())


# -- an invitation to a space -------------------------------------------------

FIXTURE_INVITE = FIXTURES / "live_space_invite.json"


def _instrument(client, calls: list) -> None:
    """Record every call of ``client`` that talks about rooms, and what
    the homeserver answers - on the client itself, so that what its own
    callbacks do is recorded too.
    """
    import nio

    def _answer(response) -> dict:
        recorded = RecordingClient._response(response)
        if isinstance(response, nio.RoomGetStateResponse):
            recorded["events"] = [
                {
                    "type": event["type"],
                    "state_key": event["state_key"],
                    "sender": event.get("sender"),
                    "content": {
                        key: event["content"][key]
                        for key in ("type", "room_version")
                        if key in event["content"]
                    },
                }
                for event in response.events
                if event.get("type") == "m.room.create"
            ]
        return recorded

    for name in ("join", "room_get_state", "room_leave", "send_message"):
        original = getattr(client, name)

        async def _call(*args, _original=original, _name=name, **kwargs):
            response = await _original(*args, **kwargs)
            calls.append(
                {
                    "method": _name,
                    "args": [a for a in args if isinstance(a, str)],
                    "response": _answer(response),
                }
            )
            return response

        setattr(client, name, _call)


async def _invite_scenario() -> None:
    """The test account is invited to a space: it accepts, and does not
    set the space up as a chat. What it does is as in the running bot -
    ``niobot`` joins, and ``_register_room_on_invite`` decides.
    """
    import nio
    import niobot
    from asgiref.sync import sync_to_async

    from matrix_jitsi_bot.bot import _add_invite_handler
    from matrix_jitsi_bot.db.models import Account, Room

    account = await sync_to_async(Account.objects.create)(
        user_id=_ACCOUNT["user_id"], homeserver=_ACCOUNT["homeserver"]
    )
    client = niobot.NioBot(
        homeserver=_ACCOUNT["homeserver"],
        user_id=_ACCOUNT["user_id"],
        device_id=_ACCOUNT["device_id"] or "matrix-jitsi-bot-test",
        command_prefix="!",
    )
    client.restore_login(
        _ACCOUNT["user_id"],
        _ACCOUNT["device_id"] or "matrix-jitsi-bot-test",
        _ACCOUNT["access_token"],
    )
    client.start_time = time.time()  # as ``start()`` does: older messages are old
    calls: list = []
    invites: list = []
    _instrument(client, calls)
    _add_invite_handler(client, account)
    client.add_event_callback(
        lambda room, event: invites.append(
            {
                "room_id": room.room_id,
                "name": room.name,
                "canonical_alias": room.canonical_alias,
                "room_type": room.room_type,
                "sender": event.sender,
                "state_key": event.state_key,
            }
        ),
        nio.InviteMemberEvent,
    )
    try:
        await client.sync(timeout=10000, full_state=True)
        mine = [i for i in invites if i["state_key"] == _ACCOUNT["user_id"]]
        if not mine:
            pytest.skip(
                f"{_ACCOUNT['user_id']} has no pending invitation - invite it to a "
                "space to run this once (an accepted invitation is used up)"
            )
        for _ in range(20):  # the callbacks run on the event loop
            if any(c["method"] == "room_get_state" for c in calls):
                break
            await asyncio.sleep(0.5)
        space_id = mine[0]["room_id"]
        for _ in range(10):  # a sync may come before the state of the space
            await client.sync(timeout=3000)
            joined = client.rooms.get(space_id)
            if joined is not None and joined.room_type == "m.space":
                break
        assert client.rooms[space_id].room_type == "m.space"
        assert not await sync_to_async(Room.objects.exists)()
        sent = [c for c in calls if c["method"] == "send_message"]
        assert not sent, "nothing is said in a space"
        assert not [c for c in calls if c["method"] == "room_leave"]
        recording = {
            "invitation": mine[0],
            "calls": calls,
            "room_type_after": client.rooms[space_id].room_type,
        }
        if os.environ.get("MJB_RECORD") == "1":
            text = json.dumps(recording, indent=2, sort_keys=True) + "\n"
            await asyncio.to_thread(FIXTURE_INVITE.write_text, text)
    finally:
        await client.close()


def test_the_bot_accepts_an_invitation_to_a_space_without_setting_it_up() -> None:
    asyncio.run(_invite_scenario())


# -- the bot is stopped while the speaker is shown ----------------------------


def _new_client():
    """A client as a bot started just now would have it - nothing synced."""
    import nio

    client = nio.AsyncClient(_ACCOUNT["homeserver"], _ACCOUNT["user_id"])
    client.restore_login(
        _ACCOUNT["user_id"],
        _ACCOUNT["device_id"] or "matrix-jitsi-bot-test",
        _ACCOUNT["access_token"],
    )
    return client


async def _restart_scenario() -> None:
    """The speaker is shown on the space, the bot is stopped, the
    conference ends, the bot is started again: the avatar comes back.
    The picture set is the one the space has already.
    """
    import nio
    from asgiref.sync import sync_to_async

    from matrix_jitsi_bot.bot import MatrixJitsiBot
    from matrix_jitsi_bot.db.models import Account, JitsiRoom, Space, TrackedJitsiRoom
    from matrix_jitsi_bot.icon.merge import SamePicture
    from matrix_jitsi_bot.interactions.avatar import AvatarInteraction

    def _bot() -> MatrixJitsiBot:
        bot = MatrixJitsiBot()
        bot.merger_with_avatar = bot.merger_without_avatar = SamePicture()
        bot.merger_space_with_avatar = SamePicture()
        return bot

    first = _new_client()
    await first.sync(timeout=10000, full_state=True)
    resolved = await first.room_resolve_alias(_SPACE_ALIAS)
    assert isinstance(resolved, nio.RoomResolveAliasResponse), resolved
    space_id = resolved.room_id
    was_member = space_id in (await first.joined_rooms()).rooms
    account = await sync_to_async(Account.objects.create)(
        user_id=first.user_id, homeserver=_ACCOUNT["homeserver"]
    )
    conversation = await sync_to_async(_chat_message)(
        account,
        _SENDER,
        f"{first.user_id}: change avatar of {_SPACE_ALIAS} when {_URL} is active",
    )
    interaction = AvatarInteraction()
    interaction.matrix_client = first
    try:
        reply = await sync_to_async(interaction.react_to_matrix_message)(conversation)
        assert reply.reaction == "✅", reply.text
        jitsi_room = await sync_to_async(JitsiRoom.objects.get)(url=_URL)
        jitsi_room.is_open = True
        await sync_to_async(jitsi_room.save)()
        await _bot().update_speaker_avatars(first)
        space = await sync_to_async(Space.objects.get)(room_id=space_id)
        assert space.speaker_shown
        original = bytes(space.original_avatar) if space.original_avatar else None
    finally:
        await first.close()

    # The bot is stopped, the conference ends, the bot is started again.
    jitsi_room.is_open = False
    await sync_to_async(jitsi_room.save)()
    second = _new_client()
    try:
        await second.sync(timeout=10000, full_state=True)
        # As in the real bot: the homeserver may not list the space as joined.
        print(
            f"the restarted client holds the space as joined: {space_id in second.rooms}"
        )
        await _bot().update_speaker_avatars(second)
        await sync_to_async(space.refresh_from_db)()
        assert not space.speaker_shown, "the avatar of the space was not restored"
        assert space.original_avatar is None
        if original is not None:
            state = await second.room_get_state_event(space_id, "m.room.avatar")
            now = (await second.download(mxc=state.content["url"])).body
            assert now == original
    finally:
        await sync_to_async(TrackedJitsiRoom.objects.all().delete)()
        await _bot().update_speaker_avatars(second)  # leaves the unused space
        if was_member:
            await second.join(_SPACE_ALIAS)
        await second.close()


def test_a_restarted_bot_restores_the_avatar_of_the_space() -> None:
    asyncio.run(_restart_scenario())
