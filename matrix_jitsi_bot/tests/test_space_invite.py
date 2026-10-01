"""The bot is invited to a space - replayed from a recording.

:file:`fixtures/live_space_invite.json` was recorded by
``test_live_avatar.py`` (with ``MJB_LIVE=1 MJB_RECORD=1``) from a real
homeserver: the invitation - which shows the name and alias of the space,
but not that it is one, so ``room_type`` is ``None`` - and what the
bot and the homeserver said to each other while the bot accepted it.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import nio
import pytest

from matrix_jitsi_bot.bot import (
    _NEEDS_CONFIGURATION_MESSAGE,
    _add_invite_handler,
    _register_room_on_invite,
)
from matrix_jitsi_bot.db.models import Account, Room
from matrix_jitsi_bot.tests.test_live_avatar import FIXTURE_INVITE

_RECORDING = json.loads(FIXTURE_INVITE.read_text())
_INVITATION = _RECORDING["invitation"]
_ROOM_ID = _INVITATION["room_id"]
_BOT = _INVITATION["state_key"]


def _recorded(method: str) -> dict:
    return next(c for c in _RECORDING["calls"] if c["method"] == method)


def _room(**changes) -> MagicMock:
    """The invited room as the bot's client saw it."""
    room = MagicMock(spec=nio.MatrixRoom)
    room.room_id = _ROOM_ID
    room.name = _INVITATION["name"]
    room.canonical_alias = _INVITATION["canonical_alias"]
    room.room_type = _INVITATION["room_type"]
    for key, value in changes.items():
        setattr(room, key, value)
    return room


def _client(*, state_events=None, join=None, state=None) -> AsyncMock:
    """A client that answers as the recorded homeserver did."""
    answer = _recorded("room_get_state")["response"]
    client = AsyncMock()
    client.user_id = _BOT
    client.join.return_value = join or nio.JoinResponse(
        _recorded("join")["response"]["room_id"]
    )
    client.room_get_state.return_value = state or nio.RoomGetStateResponse(
        answer["events"] if state_events is None else state_events,
        answer["room_id"],
    )
    return client


@pytest.fixture
def account():
    return Account.objects.create(user_id=_BOT, homeserver="https://example.org")


def _invite(client, account, room=None, *, state_key=_BOT):
    event = MagicMock(state_key=state_key, sender=_INVITATION["sender"])
    asyncio.run(_register_room_on_invite(client, account, room or _room(), event))


def test_the_recorded_invitation_does_not_say_that_it_is_a_space() -> None:
    assert _INVITATION["room_type"] is None
    assert _recorded("room_get_state")["response"]["events"][0]["content"] == {
        "room_version": "12",
        "type": "m.space",
    }
    assert _RECORDING["room_type_after"] == "m.space"


def test_an_invitation_to_a_space_is_accepted_without_setting_it_up(account) -> None:
    client = _client()

    _invite(client, account)

    client.join.assert_awaited_once_with(_ROOM_ID)
    client.room_get_state.assert_awaited_once_with(_ROOM_ID)
    client.send_message.assert_not_awaited()
    client.room_leave.assert_not_awaited()
    assert not Room.objects.exists()


def test_the_same_invitation_to_a_chat_sets_it_up(account) -> None:
    """If the state says it is no space, it is a chat as ever."""
    create = {"type": "m.room.create", "state_key": "", "content": {}}
    client = _client(state_events=[create])

    _invite(client, account)

    room = Room.objects.get()
    assert (room.room_id, room.name, room.account) == (
        _ROOM_ID,
        _INVITATION["name"],
        account,
    )
    client.send_message.assert_awaited_once_with(_ROOM_ID, _NEEDS_CONFIGURATION_MESSAGE)


def test_a_room_that_cannot_be_joined_is_taken_for_a_chat(account) -> None:
    client = _client(join=nio.JoinError("forbidden"))

    _invite(client, account)

    client.room_get_state.assert_not_awaited()
    assert Room.objects.filter(room_id=_ROOM_ID).exists()


def test_a_room_that_cannot_be_read_is_taken_for_a_chat(account) -> None:
    client = _client(state=nio.RoomGetStateError("forbidden"))

    _invite(client, account)

    assert Room.objects.filter(room_id=_ROOM_ID).exists()


@pytest.mark.no_database
def test_an_invitation_that_says_it_is_a_space_needs_no_look_at_the_state() -> None:
    client = _client()
    event = MagicMock(state_key=_BOT)
    account = MagicMock(user_id=_BOT)

    asyncio.run(
        _register_room_on_invite(client, account, _room(room_type="m.space"), event)
    )

    client.join.assert_not_awaited()
    client.room_get_state.assert_not_awaited()
    client.send_message.assert_not_awaited()


@pytest.mark.no_database
def test_a_space_that_opts_out_of_the_bot_is_left_without_joining() -> None:
    client = _client()
    event = MagicMock(state_key=_BOT)
    account = MagicMock(user_id=_BOT)

    asyncio.run(
        _register_room_on_invite(client, account, _room(name="A no-bot space"), event)
    )

    client.room_leave.assert_awaited_once_with(_ROOM_ID)
    client.join.assert_not_awaited()


@pytest.mark.no_database
def test_an_invitation_of_somebody_else_is_not_looked_at() -> None:
    client = _client()
    account = MagicMock(user_id=_BOT)

    _invite(client, account, state_key="@somebody:example.org")

    client.join.assert_not_awaited()


@pytest.mark.no_database
def test_the_client_acts_on_invitations() -> None:
    """``_add_invite_handler`` is how the running bot hears of them."""
    client = _client()
    registered = []
    client.add_event_callback = lambda callback, event_type: registered.append(
        (callback, event_type)
    )
    account = MagicMock(user_id=_BOT)

    _add_invite_handler(client, account)

    ((callback, event_type),) = registered
    assert event_type is nio.InviteMemberEvent
    asyncio.run(callback(_room(room_type="m.space"), MagicMock(state_key=_BOT)))
    client.join.assert_not_awaited()  # a space that says so, as above
