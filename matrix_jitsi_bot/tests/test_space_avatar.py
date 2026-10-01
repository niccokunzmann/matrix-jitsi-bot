"""Changing the avatar of a Matrix space for a chat that it lists."""

import asyncio
import io
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import nio
import pytest
from PIL import Image

from matrix_jitsi_bot.bot import (
    MatrixJitsiBot,
    _register_room_on_invite,
    _sync_room_members,
)
from matrix_jitsi_bot.db.models import (
    Account,
    JitsiRoom,
    Room,
    Space,
    TrackedJitsiRoom,
)
from matrix_jitsi_bot.icon.merge import SamePicture
from matrix_jitsi_bot.interactions.avatar import AvatarInteraction
from matrix_jitsi_bot.space import (
    SpaceError,
    creators_of,
    inspect_space,
    may_change_avatar,
)

_URL = "https://meet.example.org/Room"
_CHAT = "!chat:example.org"
_SPACE = "!space:example.org"
_ALIAS = "#space:example.org"
_BOT = "@bot:example.org"
_MOD = "@mod:example.org"


def _png(color="red") -> bytes:
    out = io.BytesIO()
    Image.new("RGBA", (64, 64), color).save(out, format="PNG")
    return out.getvalue()


def _state(
    *,
    children=(_CHAT,),
    levels=None,
    room_type="m.space",
    create=None,
    creator=None,
):
    """The state of a space as the homeserver reports it. ``create``
    adds to the content of its create event, ``creator`` sent it.
    """
    levels = levels or {
        "state_default": 50,
        "events": {"m.room.avatar": 50},
        "users": {_BOT: 100, _MOD: 100},
    }
    events = [
        {
            "type": "m.room.create",
            "state_key": "",
            "sender": creator,
            "content": {"type": room_type, **(create or {})},
        },
        {"type": "m.room.power_levels", "state_key": "", "content": levels},
    ]
    events += [
        {
            "type": "m.space.child",
            "state_key": child,
            "content": {"via": ["example.org"]},
        }
        for child in children
    ]
    # A removed child has empty content.
    events.append({"type": "m.space.child", "state_key": "!gone:x", "content": {}})
    return nio.RoomGetStateResponse(events, _SPACE)


def _client(*, state=None, joined=False):
    client = AsyncMock()
    client.user_id = _BOT
    client.rooms = {_SPACE: MagicMock()} if joined else {}
    client.rooms.setdefault(_CHAT, MagicMock())
    client.join.return_value = nio.JoinResponse(_SPACE)
    client.room_get_state.return_value = state or _state()
    return client


# -- the Matrix side ---------------------------------------------------


@pytest.mark.parametrize(
    ("levels", "user", "allowed"),
    [
        ({"state_default": 50, "users": {"@a:x": 50}}, "@a:x", True),
        ({"state_default": 50, "users": {"@a:x": 49}}, "@a:x", False),
        ({"events": {"m.room.avatar": 0}}, "@a:x", True),
        ({"events": {"m.room.avatar": 100}, "users": {"@a:x": 50}}, "@a:x", False),
        ({"users_default": 60}, "@a:x", True),
        ({}, "@a:x", False),
        (None, "@a:x", False),
    ],
)
@pytest.mark.no_database
def test_who_may_change_an_avatar(levels, user, allowed) -> None:
    assert may_change_avatar(levels, user) is allowed


@pytest.mark.no_database
def test_the_bot_joins_the_space_and_looks_at_it() -> None:
    client = _client()

    check = asyncio.run(inspect_space(client, _ALIAS, _CHAT, _MOD))

    client.join.assert_awaited_once_with(_ALIAS)
    assert check.room_id == _SPACE
    assert check.joined_now
    assert check.lists_chat
    assert check.user_may_change_avatar
    assert check.bot_may_change_avatar


@pytest.mark.no_database
def test_the_bot_does_not_join_a_space_it_is_in() -> None:
    client = _client(joined=True)

    check = asyncio.run(inspect_space(client, _SPACE, _CHAT, _MOD))

    client.join.assert_not_awaited()
    assert not check.joined_now


@pytest.mark.no_database
def test_a_space_that_lists_other_rooms_only() -> None:
    client = _client(state=_state(children=("!other:example.org",)))
    assert not asyncio.run(inspect_space(client, _ALIAS, _CHAT, _MOD)).lists_chat


@pytest.mark.no_database
def test_a_removed_child_is_not_listed() -> None:
    client = _client(state=_state(children=()))
    check = asyncio.run(inspect_space(client, _ALIAS, "!gone:x", _MOD))
    assert not check.lists_chat


@pytest.mark.no_database
def test_a_user_without_the_power_may_not_change_the_avatar() -> None:
    levels = {"state_default": 50, "users": {_BOT: 100}}
    client = _client(state=_state(levels=levels))
    check = asyncio.run(inspect_space(client, _ALIAS, _CHAT, _MOD))
    assert not check.user_may_change_avatar
    assert check.bot_may_change_avatar


@pytest.mark.no_database
def test_a_room_that_is_no_space_is_left_again() -> None:
    client = _client(state=_state(room_type="m.room"))
    with pytest.raises(SpaceError, match="is not a space"):
        asyncio.run(inspect_space(client, _ALIAS, _CHAT, _MOD))
    client.room_leave.assert_awaited_once_with(_SPACE)


@pytest.mark.no_database
def test_a_space_that_cannot_be_joined() -> None:
    client = _client()
    client.join.return_value = nio.JoinError("not invited")
    with pytest.raises(SpaceError, match=r"could not join #space:example\.org"):
        asyncio.run(inspect_space(client, _ALIAS, _CHAT, _MOD))
    client.room_leave.assert_not_awaited()


# -- the commands --------------------------------------------------------


@pytest.fixture
def chat(send_message, make_moderator):
    """A chat of the bot account, with a moderator."""
    account = Account.objects.create(user_id=_BOT, homeserver="https://example.org")

    def _send(body: str, sender: str = _MOD):
        conv = send_message(body, room_id=_CHAT, sender=sender)
        conv.room.account = account
        conv.room.save()
        make_moderator(conv, _MOD)
        return conv

    return _send


def _run(conv, client, *, can_set_avatar=True):
    interaction = AvatarInteraction()
    interaction.matrix_client = client
    interaction.can_set_avatar = can_set_avatar
    return interaction.react_to_matrix_message(conv)


def test_a_space_that_lists_the_chat_is_set_up(chat) -> None:
    client = _client()
    conv = chat(f"@bot: change avatar of {_ALIAS} when {_URL} is active")

    result = _run(conv, client)

    assert result.reaction == "✅"
    assert result.text == (
        f"Now tracking {_URL}. A speaker is shown on the avatar of {_ALIAS} "
        "while it is active."
    )
    space = Space.objects.get()
    assert (space.room_id, space.alias) == (_SPACE, _ALIAS)
    tracked = TrackedJitsiRoom.objects.get()
    assert list(tracked.avatar_spaces.all()) == [space]
    assert not tracked.show_speaker  # the chat's own avatar is not changed
    client.room_leave.assert_not_awaited()


def test_a_space_does_not_need_the_bot_to_change_the_avatar_of_the_chat(chat) -> None:
    conv = chat(f"@bot: change avatar of {_ALIAS} when {_URL} is active")
    assert _run(conv, _client(), can_set_avatar=False).reaction == "✅"


def test_a_space_that_does_not_list_the_chat_is_reported_and_left(chat) -> None:
    client = _client(state=_state(children=("!other:example.org",)))
    conv = chat(f"@bot: change avatar of {_ALIAS} when {_URL} is active")

    result = _run(conv, client)

    assert result.reaction == "❌"
    assert f"{_ALIAS} does not list this chat" in result.text
    client.room_leave.assert_awaited_once_with(_SPACE)
    assert not Space.objects.exists()
    assert not TrackedJitsiRoom.objects.exists()


def test_a_user_who_may_not_change_the_space_avatar_is_refused(chat) -> None:
    levels = {"state_default": 50, "users": {_BOT: 100}}
    client = _client(state=_state(levels=levels))
    conv = chat(f"@bot: change avatar of {_ALIAS} when {_URL} is active")

    result = _run(conv, client)

    assert result.reaction == "❌"
    assert "You are not allowed to change the avatar of #space:example.org" in (
        result.text
    )
    client.room_leave.assert_not_awaited()  # it stays: nobody has to invite it again
    assert not TrackedJitsiRoom.objects.exists()


def test_the_bot_reports_that_it_may_not_change_the_space_avatar(chat) -> None:
    levels = {"state_default": 50, "users": {_MOD: 100}}
    client = _client(state=_state(levels=levels))
    conv = chat(f"@bot: change avatar of {_ALIAS} when {_URL} is active")

    result = _run(conv, client)

    assert result.reaction == "❌"
    assert "I am not allowed to change the avatar of #space:example.org" in result.text
    client.room_leave.assert_not_awaited()  # it stays: nobody has to invite it again
    assert not TrackedJitsiRoom.objects.exists()


def test_a_space_the_bot_cannot_join_is_reported(chat) -> None:
    client = _client()
    client.join.return_value = nio.JoinError("not invited")
    conv = chat(f"@bot: change avatar of {_ALIAS} when {_URL} is active")

    result = _run(conv, client)

    assert result.reaction == "❌"
    assert "I could not join #space:example.org" in result.text


def test_only_moderators_change_the_avatar_of_a_space(chat) -> None:
    client = _client()
    conv = chat(
        f"@bot: change avatar of {_ALIAS} when {_URL} is active",
        sender="@user:example.org",
    )

    result = _run(conv, client)

    assert "only room moderators" in result.text
    client.join.assert_not_awaited()


def test_a_space_stays_if_the_conference_is_invalid(chat, monkeypatch) -> None:
    async def _boom(url, *, want_participants=True, name=None):
        raise ConnectionError("no")

    monkeypatch.setattr("matrix_jitsi_bot.jitsi.check_jitsi_room", _boom)
    client = _client()
    conv = chat(f"@bot: change avatar of {_ALIAS} when {_URL} is active")

    result = _run(conv, client)

    assert result.reaction == "❌"
    client.room_leave.assert_not_awaited()
    assert not Space.objects.exists()


@pytest.mark.parametrize("this", ["this chat", "this room"])
def test_this_chat_and_this_room_are_the_same_as_no_target(chat, this) -> None:
    conv = chat(f"@bot: change avatar of {this} when {_URL} is active")

    result = _run(conv, _client())

    assert result.reaction == "✅"
    assert TrackedJitsiRoom.objects.get().show_speaker
    assert not Space.objects.exists()


def test_this_chat_is_refused_if_the_bot_may_not_change_its_avatar(chat) -> None:
    conv = chat(f"@bot: change avatar of this chat when {_URL} is active")

    result = _run(conv, _client(), can_set_avatar=False)

    assert "I am not allowed to change this room's avatar" in result.text
    assert not TrackedJitsiRoom.objects.exists()


def test_the_chat_and_a_space_can_both_change(chat) -> None:
    _run(chat(f"@bot: change avatar when {_URL} is active"), _client())
    _run(chat(f"@bot: change avatar of {_ALIAS} when {_URL} is active"), _client())

    tracked = TrackedJitsiRoom.objects.get()
    assert tracked.show_speaker
    assert tracked.avatar_spaces.count() == 1


def test_a_space_is_given_up(chat) -> None:
    _run(chat(f"@bot: change avatar of {_ALIAS} when {_URL} is active"), _client())

    result = _run(
        chat(f"@bot: don't change avatar of {_ALIAS} when {_URL} is active"),
        _client(),
    )

    assert result.reaction == "✅"
    assert not TrackedJitsiRoom.objects.exists()  # nothing is tracked anymore


def test_giving_up_a_space_keeps_the_avatar_of_the_chat(chat) -> None:
    _run(chat(f"@bot: change avatar when {_URL} is active"), _client())
    _run(chat(f"@bot: change avatar of {_ALIAS} when {_URL} is active"), _client())

    _run(
        chat(f"@bot: don't change avatar of {_ALIAS} when {_URL} is active"), _client()
    )

    tracked = TrackedJitsiRoom.objects.get()
    assert tracked.show_speaker
    assert tracked.avatar_spaces.count() == 0


def test_giving_up_a_space_that_was_not_set_up(chat) -> None:
    _run(chat(f"@bot: change avatar when {_URL} is active"), _client())

    result = _run(
        chat(f"@bot: don't change avatar of {_ALIAS} when {_URL} is active"),
        _client(),
    )

    assert result.reaction == "❌"
    assert "I do not change the avatar of #space:example.org" in result.text


# -- the avatar --------------------------------------------------------


@pytest.fixture
def space_setup():
    account = Account.objects.create(user_id=_BOT, homeserver="https://example.org")
    room = Room.objects.create(room_id=_CHAT, account=account)
    jitsi_room = JitsiRoom.objects.create(url=_URL)
    space = Space.objects.create(room_id=_SPACE, alias=_ALIAS, account=account)
    tracked = TrackedJitsiRoom.objects.create(room=room, jitsi_room=jitsi_room)
    tracked.avatar_spaces.add(space)
    return room, jitsi_room, space


def _space_state(*, avatar_url="mxc://example.org/space", bot_level=100):
    """The state of the space that matters for its avatar."""
    events = [
        {"type": "m.room.create", "state_key": "", "content": {"type": "m.space"}},
        {
            "type": "m.room.power_levels",
            "state_key": "",
            "content": {"state_default": 50, "users": {_BOT: bot_level}},
        },
    ]
    if avatar_url:
        events.append(
            {"type": "m.room.avatar", "state_key": "", "content": {"url": avatar_url}}
        )
    return nio.RoomGetStateResponse(events, _SPACE)


def _space_client(avatar_url="mxc://example.org/space", *, bot_level=100):
    """A client whose homeserver tells about the space - and that knows it as
    a joined room, as ``nio`` does while the bot has not been restarted.
    """
    client = AsyncMock()
    client.user_id = _BOT
    matrix_space = MagicMock(spec=nio.MatrixRoom)
    matrix_space.room_avatar_url = avatar_url
    client.rooms = {_SPACE: matrix_space}
    client.room_get_state.return_value = _space_state(
        avatar_url=avatar_url, bot_level=bot_level
    )
    client.download.return_value = nio.MemoryDownloadResponse(_png(), "image/png", None)
    client.upload.return_value = (
        SimpleNamespace(content_uri="mxc://example.org/new"),
        None,
    )
    client.room_put_state.return_value = SimpleNamespace()
    return client


def _update(bot, client):
    asyncio.run(bot.update_speaker_avatars(client))


def test_the_avatar_of_the_space_changes_while_the_conference_is_active(
    space_setup,
) -> None:
    _, jitsi_room, space = space_setup
    client = _space_client()
    bot = MatrixJitsiBot()

    _update(bot, client)
    client.room_put_state.assert_not_awaited()  # closed

    jitsi_room.is_open = True
    jitsi_room.save()
    _update(bot, client)

    space.refresh_from_db()
    assert space.speaker_shown
    assert bytes(space.original_avatar) == _png()
    client.room_put_state.assert_awaited_once_with(
        _SPACE, "m.room.avatar", {"url": "mxc://example.org/new"}, state_key=""
    )

    jitsi_room.is_open = False
    jitsi_room.save()
    _update(bot, client)

    space.refresh_from_db()
    assert not space.speaker_shown
    assert space.original_avatar is None
    assert client.upload.await_args.args[0].getvalue() == _png()
    assert client.room_put_state.await_count == 2


def test_a_paused_chat_does_not_change_the_avatar_of_the_space(space_setup) -> None:
    room, jitsi_room, _ = space_setup
    room.paused = True
    room.save()
    jitsi_room.is_open = True
    jitsi_room.save()
    client = _space_client()

    _update(MatrixJitsiBot(), client)

    client.room_put_state.assert_not_awaited()


def test_the_space_avatar_stays_while_another_chat_has_an_active_conference(
    space_setup,
) -> None:
    _, jitsi_room, space = space_setup
    other_room = Room.objects.create(
        room_id="!other:example.org", account=space.account
    )
    other_jitsi = JitsiRoom.objects.create(url=_URL + "2", is_open=True)
    other = TrackedJitsiRoom.objects.create(room=other_room, jitsi_room=other_jitsi)
    other.avatar_spaces.add(space)
    jitsi_room.is_open = True
    jitsi_room.save()
    client = _space_client()
    bot = MatrixJitsiBot()
    _update(bot, client)

    jitsi_room.is_open = False
    jitsi_room.save()
    _update(bot, client)

    space.refresh_from_db()
    assert space.speaker_shown  # the other conference is still active
    assert client.room_put_state.await_count == 1


def test_a_space_that_is_given_up_is_restored_and_then_left(space_setup) -> None:
    _, jitsi_room, _space = space_setup
    jitsi_room.is_open = True
    jitsi_room.save()
    client = _space_client()
    bot = MatrixJitsiBot()
    _update(bot, client)
    TrackedJitsiRoom.objects.all().delete()

    _update(bot, client)

    assert client.room_put_state.await_count == 2  # restored first
    assert client.upload.await_args.args[0].getvalue() == _png()
    client.room_leave.assert_awaited_once_with(_SPACE)
    assert not Space.objects.exists()


def test_the_speaker_is_at_the_bottom_right_of_a_space_avatar(space_setup) -> None:
    """Not at the top right like on a chat: the full speaker, 1/2 as wide."""
    _, jitsi_room, _ = space_setup
    jitsi_room.is_open = True
    jitsi_room.save()
    client = _space_client()  # its avatar is 64 x 64 pixels, all red

    _update(MatrixJitsiBot(), client)

    shown = Image.open(client.upload.await_args.args[0]).convert("RGBA")
    red = (255, 0, 0, 255)
    assert shown.size == (64, 64)
    assert shown.getpixel((48, 48)) != red  # the speaker: x and y 32..63
    assert shown.getpixel((60, 4)) == red  # the top right is free
    assert shown.getpixel((4, 4)) == red
    assert shown.getpixel((20, 48)) == red  # left of it


def test_the_same_picture_can_be_set_for_a_change_nobody_sees(space_setup) -> None:
    _, jitsi_room, _ = space_setup
    jitsi_room.is_open = True
    jitsi_room.save()
    client = _space_client()
    bot = MatrixJitsiBot()
    bot.merger_space_with_avatar = SamePicture()
    bot.merger_without_avatar = SamePicture()

    _update(bot, client)

    shown = Image.open(client.upload.await_args.args[0])
    assert list(shown.convert("RGBA").getdata()) == list(
        Image.open(io.BytesIO(_png())).convert("RGBA").getdata()
    )


def test_a_space_without_avatar_gets_none_set_by_the_same_picture(space_setup) -> None:
    _, jitsi_room, _ = space_setup
    jitsi_room.is_open = True
    jitsi_room.save()
    client = _space_client(avatar_url=None)
    bot = MatrixJitsiBot()
    bot.merger_without_avatar = SamePicture()

    _update(bot, client)

    client.upload.assert_not_awaited()
    client.room_put_state.assert_awaited_once_with(
        _SPACE, "m.room.avatar", {}, state_key=""
    )


def test_a_space_that_nio_does_not_hold_is_changed_all_the_same(space_setup) -> None:
    """The homeserver may list a joined space as an invitation, so the
    client does not hold it - its state is asked of the homeserver."""
    _, jitsi_room, space = space_setup
    jitsi_room.is_open = True
    jitsi_room.save()
    client = _space_client()
    client.rooms = {}

    _update(MatrixJitsiBot(), client)

    space.refresh_from_db()
    assert space.speaker_shown
    client.room_get_state.assert_awaited_with(_SPACE)
    client.room_put_state.assert_awaited_once()


def test_a_space_that_cannot_be_read_is_tried_again_later(space_setup) -> None:
    _, jitsi_room, space = space_setup
    jitsi_room.is_open = True
    jitsi_room.save()
    client = _space_client()
    client.room_get_state.return_value = nio.RoomGetStateError("forbidden")
    bot = MatrixJitsiBot()

    _update(bot, client)

    client.room_put_state.assert_not_awaited()
    space.refresh_from_db()
    assert not space.speaker_shown
    assert _SPACE in bot._speaker_retry_at


# -- spaces are not chats -------------------------------------------------


def test_an_invite_to_a_space_is_accepted_without_setting_up_a_chat() -> None:
    account = Account.objects.create(user_id=_BOT, homeserver="https://example.org")
    client = AsyncMock()
    space = MagicMock(room_id=_SPACE, room_type="m.space")
    space.name = "A space"
    event = MagicMock(state_key=_BOT)

    asyncio.run(_register_room_on_invite(client, account, space, event))

    assert not Room.objects.exists()
    client.send_message.assert_not_awaited()
    client.room_leave.assert_not_awaited()


def test_an_invite_to_a_chat_still_sets_it_up() -> None:
    account = Account.objects.create(user_id=_BOT, homeserver="https://example.org")
    client = AsyncMock()
    chat = MagicMock(room_id=_CHAT, room_type=None)
    chat.name = "A chat"
    event = MagicMock(state_key=_BOT)

    asyncio.run(_register_room_on_invite(client, account, chat, event))

    assert Room.objects.filter(room_id=_CHAT).exists()
    client.send_message.assert_awaited_once()


def test_members_of_a_space_are_not_recorded() -> None:
    account = Account.objects.create(user_id=_BOT, homeserver="https://example.org")
    space = MagicMock(room_id=_SPACE, room_type="m.space")
    space.users = {"@a:example.org": None}
    space.invited_users = {}

    asyncio.run(_sync_room_members(account, space, MagicMock(state_key="@a:x")))

    assert not Room.objects.exists()


def test_a_joined_space_is_not_set_up_as_a_chat_at_startup() -> None:
    account = Account.objects.create(user_id=_BOT, homeserver="https://example.org")
    client = AsyncMock()
    chat = MagicMock(room_type=None)
    chat.name = "A chat"
    client.rooms = {_SPACE: MagicMock(room_type="m.space"), _CHAT: chat}

    asyncio.run(MatrixJitsiBot.reconcile_joined_rooms(client, account))

    assert [room.room_id for room in Room.objects.all()] == [_CHAT]
    assert client.send_message.await_count == 1


def test_a_space_the_bot_leaves_and_rejoins_keeps_what_chats_asked_for(
    space_setup,
) -> None:
    """The bot's membership may change for other reasons than that it
    does not need the space: a chat that asked for it must not lose it."""
    from matrix_jitsi_bot.bot import _forget_left_rooms

    _, _, space = space_setup
    response = MagicMock()
    response.rooms.leave = {_SPACE: MagicMock()}

    asyncio.run(_forget_left_rooms(response))

    assert Space.objects.get() == space
    assert space.tracked_by.count() == 1  # still asked for by the chat


# -- creators of room version 12 ------------------------------------------


@pytest.mark.parametrize(
    ("create", "creators"),
    [
        ({"room_version": "12", "sender": "@c:x"}, {"@c:x"}),
        ({"room_version": "13", "sender": "@c:x"}, {"@c:x"}),
        (
            {
                "room_version": "12",
                "sender": "@c:x",
                "content_extra": {"additional_creators": ["@d:x"]},
            },
            {"@c:x", "@d:x"},
        ),
        ({"room_version": "org.matrix.hydra.11", "sender": "@c:x"}, {"@c:x"}),
        ({"room_version": "11", "sender": "@c:x"}, set()),
        ({"room_version": "1", "sender": "@c:x"}, set()),
        ({"sender": "@c:x"}, set()),  # no version: version 1
    ],
)
@pytest.mark.no_database
def test_who_are_the_creators_with_unlimited_power(create, creators) -> None:
    content = {
        k: v for k, v in create.items() if k not in ("sender", "content_extra")
    } | create.get("content_extra", {})
    event = {"type": "m.room.create", "sender": create["sender"], "content": content}

    assert creators_of(event) == creators


@pytest.mark.no_database
def test_there_are_no_creators_without_a_create_event() -> None:
    assert creators_of(None) == frozenset()


@pytest.mark.no_database
def test_a_creator_may_change_the_avatar_without_being_in_the_power_levels() -> None:
    assert may_change_avatar({"state_default": 50}, "@c:x", frozenset({"@c:x"}))
    assert may_change_avatar(None, "@c:x", frozenset({"@c:x"}))
    assert not may_change_avatar({"state_default": 50}, "@d:x", frozenset({"@c:x"}))


@pytest.mark.no_database
def test_the_creator_of_a_version_12_space_may_change_its_avatar() -> None:
    """In version 12 the creators are not in the power levels at all."""
    levels = {"state_default": 50, "users": {}}
    state = _state(levels=levels, create={"room_version": "12"}, creator=_MOD)
    client = _client(state=state)

    check = asyncio.run(inspect_space(client, _ALIAS, _CHAT, _MOD))

    assert check.user_may_change_avatar
    assert not check.bot_may_change_avatar


@pytest.mark.no_database
def test_the_bot_may_be_a_creator_of_a_version_12_space() -> None:
    levels = {"state_default": 50, "users": {}}
    state = _state(
        levels=levels,
        create={"room_version": "12", "additional_creators": [_BOT]},
        creator="@admin:example.org",
    )
    client = _client(state=state)

    check = asyncio.run(inspect_space(client, _ALIAS, _CHAT, _MOD))

    assert check.bot_may_change_avatar
    assert not check.user_may_change_avatar


@pytest.mark.no_database
def test_the_creator_of_an_older_space_has_no_power_unless_it_is_listed() -> None:
    levels = {"state_default": 50, "users": {}}
    state = _state(levels=levels, create={"room_version": "11"}, creator=_MOD)

    check = asyncio.run(inspect_space(_client(state=state), _ALIAS, _CHAT, _MOD))

    assert not check.user_may_change_avatar


# -- the message pipeline ---------------------------------------------------


def _dispatch(body: str, client, *, sender: str = _MOD):
    """Handle a message of ``sender`` as the bot does: with the live
    client, on the event loop, the handler in a worker thread.
    """
    from datetime import UTC, datetime

    from matrix_jitsi_bot.db.models import RoomMember

    interaction = AvatarInteraction()
    client.send_message = AsyncMock()
    client.add_reaction = AsyncMock()
    chat = nio.MatrixRoom(_CHAT, _BOT)
    chat.power_levels.defaults.state_default = 50
    stored = Room.objects.create(room_id=_CHAT)
    RoomMember.objects.create(room=stored, user_id=_MOD, power_level=50)
    event = MagicMock(
        sender=sender,
        body=body,
        event_id="$space1",
        server_timestamp=int(datetime.now(tz=UTC).timestamp() * 1000),
        source={},
    )

    asyncio.run(interaction.on_matrix_message(client, chat, event))

    return interaction


def test_a_space_is_set_up_by_a_message_of_a_moderator() -> None:
    client = _client()

    interaction = _dispatch(
        f"{_BOT}: change avatar of {_ALIAS} when {_URL} is active", client
    )

    client.join.assert_awaited_once_with(_ALIAS)  # on the event loop
    assert client.send_message.await_args.args[1].startswith(f"Now tracking {_URL}.")
    assert Space.objects.get().room_id == _SPACE
    assert interaction.matrix_client is None  # not kept after the message


def test_a_space_that_does_not_list_the_chat_is_left_after_a_message() -> None:
    client = _client(state=_state(children=()))

    _dispatch(f"{_BOT}: change avatar of {_ALIAS} when {_URL} is active", client)

    assert "does not list this chat" in client.send_message.await_args.args[1]
    client.room_leave.assert_awaited_once_with(_SPACE)


# -- other ways to name or share a space ----------------------------------


def test_a_space_can_be_named_by_its_room_id(chat) -> None:
    client = _client()
    conv = chat(f"@bot: change avatar of {_SPACE} when {_URL} is active")

    result = _run(conv, client)

    assert result.reaction == "✅"
    client.join.assert_awaited_once_with(_SPACE)
    space = Space.objects.get()
    assert (space.room_id, space.alias) == (_SPACE, "")


def test_a_space_named_by_its_room_id_is_given_up_by_that_name(chat) -> None:
    _run(chat(f"@bot: change avatar of {_SPACE} when {_URL} is active"), _client())

    result = _run(
        chat(f"@bot: don't change avatar of {_SPACE} when {_URL} is active"),
        _client(),
    )

    assert result.reaction == "✅"
    assert not TrackedJitsiRoom.objects.exists()


def test_a_space_the_bot_is_in_is_found_by_its_canonical_alias(chat) -> None:
    client = _client(joined=True)
    client.rooms[_SPACE].canonical_alias = _ALIAS
    conv = chat(f"@bot: change avatar of {_ALIAS} when {_URL} is active")

    result = _run(conv, client)

    assert result.reaction == "✅"
    client.join.assert_not_awaited()


def test_a_space_the_bot_was_in_is_not_left_when_it_is_refused(chat) -> None:
    """A space of another chat stays, whatever this chat asks of it."""
    _run(chat(f"@bot: change avatar of {_ALIAS} when {_URL} is active"), _client())
    client = _client(state=_state(children=()), joined=True)
    client.rooms[_SPACE].canonical_alias = _ALIAS
    conv = chat(f"@bot: change avatar of {_ALIAS} when {_URL}2 is active")

    result = _run(conv, client)

    assert result.reaction == "❌"
    client.room_leave.assert_not_awaited()
    assert Space.objects.get().is_used()


def test_a_space_that_one_chat_gives_up_stays_for_the_other(space_setup) -> None:
    room, _jitsi_room, space = space_setup
    other_room = Room.objects.create(
        room_id="!other:example.org", account=space.account
    )
    other_jitsi = JitsiRoom.objects.create(url=_URL + "2", is_open=True)
    other = TrackedJitsiRoom.objects.create(room=other_room, jitsi_room=other_jitsi)
    other.avatar_spaces.add(space)
    client = _space_client()
    bot = MatrixJitsiBot()
    _update(bot, client)

    TrackedJitsiRoom.objects.filter(room=room).delete()  # the first gives up
    _update(bot, client)

    client.room_leave.assert_not_awaited()
    space.refresh_from_db()
    assert space.speaker_shown  # the other conference is still active
    assert client.room_put_state.await_count == 1


def test_a_space_that_shows_the_speaker_keeps_the_bot_polling_often(
    space_setup, monkeypatch
) -> None:
    """With nothing else tracked, a space showing the speaker must still
    be looked after soon - not after the long idle sleep."""
    from matrix_jitsi_bot.bot import _IDLE_POLL_INTERVAL

    _, _, space = space_setup
    TrackedJitsiRoom.objects.all().delete()
    space.speaker_shown = True
    space.save()
    sleeps = []

    async def _fake_sleep(seconds):
        sleeps.append(seconds)
        raise asyncio.CancelledError

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(MatrixJitsiBot().poll_jitsi_rooms_forever(AsyncMock(), wait=1))

    assert sleeps == [1]
    assert sleeps != [_IDLE_POLL_INTERVAL]


def test_a_space_the_bot_lost_the_power_for_is_tried_again_later(space_setup) -> None:
    _, jitsi_room, space = space_setup
    jitsi_room.is_open = True
    jitsi_room.save()
    client = _space_client(bot_level=0)
    bot = MatrixJitsiBot()

    _update(bot, client)  # refused, and not tried again at once
    _update(bot, client)

    client.room_put_state.assert_not_awaited()
    space.refresh_from_db()
    assert not space.speaker_shown

    client.room_get_state.return_value = _space_state(bot_level=100)
    bot._speaker_retry_at.clear()  # the waiting time is over
    _update(bot, client)

    space.refresh_from_db()
    assert space.speaker_shown
    client.room_put_state.assert_awaited_once()


# -- a space the bot is not in and not invited to -----------------------------


def _not_invited(client) -> None:
    client.join.return_value = nio.JoinError("You are not invited", "M_FORBIDDEN")


@pytest.mark.no_database
def test_a_space_without_invitation_asks_for_one_first() -> None:
    client = _client()
    _not_invited(client)

    with pytest.raises(SpaceError) as error:
        asyncio.run(inspect_space(client, _ALIAS, _CHAT, _MOD))

    message = str(error.value)
    assert f"I am not in {_ALIAS} and I am not invited to it" in message
    assert "invite me to the space first" in message
    assert "then give me the power to change its avatar" in message
    assert "moderator" in message
    client.room_get_state.assert_not_awaited()
    client.room_leave.assert_not_awaited()  # it was never in


def test_the_reply_asks_for_an_invitation_and_then_for_the_power(chat) -> None:
    client = _client()
    _not_invited(client)
    conv = chat(f"@bot: change avatar of {_ALIAS} when {_URL} is active")

    result = _run(conv, client)

    assert result.reaction == "❌"
    assert result.text.startswith(f"I am not in {_ALIAS} and I am not invited to it.")
    assert not Space.objects.exists()
    assert not TrackedJitsiRoom.objects.exists()


def test_other_reasons_not_to_join_are_still_told_as_they_are(chat) -> None:
    client = _client()
    client.join.return_value = nio.JoinError("Unknown room", "M_NOT_FOUND")
    conv = chat(f"@bot: change avatar of {_ALIAS} when {_URL} is active")

    result = _run(conv, client)

    assert "I could not join #space:example.org: Unknown room" in result.text


def test_the_bot_without_the_power_is_told_to_be_a_moderator(chat) -> None:
    levels = {"state_default": 50, "users": {_MOD: 100}}
    conv = chat(f"@bot: change avatar of {_ALIAS} when {_URL} is active")

    result = _run(conv, _client(state=_state(levels=levels)))

    assert "in most spaces that is being a moderator" in result.text


# -- the bot is stopped while the speaker is shown ----------------------------


def _chat_room(avatar_url="mxc://example.org/chat") -> MagicMock:
    """The chat as ``nio`` holds it: joined, the bot may change its avatar."""
    chat = MagicMock(spec=nio.MatrixRoom)
    chat.room_avatar_url = avatar_url
    chat.power_levels = nio.PowerLevels()
    chat.power_levels.defaults.state_default = 50
    chat.power_levels.users[_BOT] = 100
    return chat


def test_after_a_restart_the_avatars_of_the_chat_and_of_the_space_come_back(
    space_setup,
) -> None:
    """The bot is stopped while the speaker is shown on both, the
    conference closes meanwhile, and the bot is started again: its new
    client does not know the space as a joined room - the homeserver
    lists it as an invitation still - but must restore it all the same.
    """
    room, jitsi_room, space = space_setup
    TrackedJitsiRoom.objects.filter(room=room).update(show_speaker=True)
    jitsi_room.is_open = True
    jitsi_room.save()
    before = _space_client()
    before.rooms[_CHAT] = _chat_room()
    _update(MatrixJitsiBot(), before)
    room.refresh_from_db()
    space.refresh_from_db()
    assert room.speaker_shown
    assert space.speaker_shown

    # The bot is stopped, the conference ends, the bot is started again.
    jitsi_room.is_open = False
    jitsi_room.save()
    after = _space_client()
    after.rooms = {_CHAT: _chat_room()}  # not the space
    _update(MatrixJitsiBot(), after)

    room.refresh_from_db()
    space.refresh_from_db()
    assert not room.speaker_shown
    assert not space.speaker_shown
    assert {c.args[0] for c in after.room_put_state.await_args_list} == {_CHAT, _SPACE}


def test_nothing_is_tried_before_the_first_sync_and_all_comes_back_after_it(
    space_setup,
) -> None:
    """A started bot polls at once - before it has logged in and synced.
    That must not fail and then wait: the avatars come back right after."""
    room, jitsi_room, space = space_setup
    TrackedJitsiRoom.objects.filter(room=room).update(show_speaker=True)
    jitsi_room.is_open = True
    jitsi_room.save()
    shown = _space_client()
    shown.rooms[_CHAT] = _chat_room()
    _update(MatrixJitsiBot(), shown)
    jitsi_room.is_open = False  # it ended while the bot was stopped
    jitsi_room.save()

    bot = MatrixJitsiBot()
    started = _space_client()
    started.rooms = {}
    started.next_batch = ""  # not synced
    _update(bot, started)

    started.room_put_state.assert_not_awaited()
    started.room_get_state.assert_not_awaited()
    assert bot._speaker_retry_at == {}  # no waiting time was started

    started.next_batch = "s1"  # the first sync is done
    started.rooms = {_CHAT: _chat_room()}
    _update(bot, started)

    room.refresh_from_db()
    space.refresh_from_db()
    assert not room.speaker_shown
    assert not space.speaker_shown


def test_a_run_that_checks_once_puts_the_avatars_back_too(space_setup) -> None:
    """``run --once`` after the conference ended while the bot was stopped:
    it checks every conference, and the avatars follow what it finds."""
    room, jitsi_room, space = space_setup
    TrackedJitsiRoom.objects.filter(room=room).update(show_speaker=True)
    jitsi_room.is_open = True  # as of the last run
    jitsi_room.save()
    client = _space_client()
    client.rooms[_CHAT] = _chat_room()
    _update(MatrixJitsiBot(), client)
    room.refresh_from_db()
    space.refresh_from_db()
    assert room.speaker_shown
    assert space.speaker_shown

    # By default a check finds a conference closed - it has ended.
    checked = asyncio.run(MatrixJitsiBot().poll_jitsi_rooms_all(client))

    assert checked == 1
    room.refresh_from_db()
    space.refresh_from_db()
    assert not room.speaker_shown
    assert not space.speaker_shown
