"""Looking at a Matrix space: joining it, and what it lists and allows.

:py:func:`~matrix_jitsi_bot.space.inspect_space` answers what the bot
needs to know before it may change a space's avatar for a chat - see
:py:class:`~matrix_jitsi_bot.interactions.avatar.AvatarInteraction`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import nio

#: The state event type that gives a room its avatar.
AVATAR_EVENT = "m.room.avatar"

#: The power level that changes state, if the room says nothing else.
_DEFAULT_STATE_LEVEL = 50

#: From this room version on, a room's creators have unlimited power.
_CREATORS_FROM_VERSION = 12


class SpaceError(Exception):
    """The space cannot be looked at - its message is for the chat."""


@dataclass
class SpaceCheck:
    """What :py:func:`~matrix_jitsi_bot.space.inspect_space` found."""

    room_id: str
    joined_now: bool
    """Whether the bot joined the space for this check."""
    lists_chat: bool
    """Whether the space lists the chat as one of its rooms."""
    user_may_change_avatar: bool
    bot_may_change_avatar: bool


def creators_of(create_event: dict | None) -> frozenset[str]:
    """The users with unlimited power in a room: its creators - in room
    version 12 and later, whose creators are not listed in the power
    levels. Empty for older rooms, where the power levels say it all.
    """
    if not create_event:
        return frozenset()
    content = create_event.get("content", {})
    version = str(content.get("room_version", "1"))
    if version != "org.matrix.hydra.11" and not (
        version.isdigit() and int(version) >= _CREATORS_FROM_VERSION
    ):
        return frozenset()
    creators = set(content.get("additional_creators", []))
    if create_event.get("sender"):
        creators.add(create_event["sender"])
    return frozenset(creators)


def may_change_avatar(
    power_levels: dict | None, user_id: str, creators: frozenset[str] = frozenset()
) -> bool:
    """Whether ``user_id`` may change the avatar of a room whose
    ``m.room.power_levels`` content is ``power_levels`` and whose
    creators with unlimited power are ``creators`` - see
    :py:func:`~matrix_jitsi_bot.space.creators_of`.
    """
    if user_id in creators:
        return True
    if not power_levels:
        return False
    required = power_levels.get("events", {}).get(
        AVATAR_EVENT, power_levels.get("state_default", _DEFAULT_STATE_LEVEL)
    )
    level = power_levels.get("users", {}).get(
        user_id, power_levels.get("users_default", 0)
    )
    return level >= required


def _event(events: list[dict], event_type: str, state_key: str = "") -> dict | None:
    """The state event ``event_type`` with ``state_key``."""
    for event in events:
        if event.get("type") == event_type and event.get("state_key") == state_key:
            return event
    return None


def _content(events: list[dict], event_type: str, state_key: str = "") -> dict | None:
    """The content of the state event ``event_type`` with ``state_key``."""
    event = _event(events, event_type, state_key)
    return None if event is None else event.get("content", {})


async def inspect_space(
    client: nio.AsyncClient, ref: str, chat_room_id: str, sender: str
) -> SpaceCheck:
    """Join the space ``ref`` - its alias or room ID - unless the bot is
    in it already, and look at it for the chat ``chat_room_id`` that
    ``sender`` writes in.

    Raises :py:exc:`~matrix_jitsi_bot.space.SpaceError` if it cannot be
    joined or read, or is not a space. The bot leaves it again then,
    if it joined it just now.
    """
    import nio

    room_id = _joined_room_id(client, ref)
    if room_id is None:
        joined = await client.join(ref)
        if isinstance(joined, nio.JoinError):
            if joined.status_code == "M_FORBIDDEN":
                raise SpaceError(
                    f"I am not in {ref} and I am not invited to it. Please invite "
                    "me to the space first, then give me the power to change its "
                    "avatar - in most spaces that is being a moderator - and ask "
                    "again."
                )
            raise SpaceError(f"I could not join {ref}: {joined.message}")
        room_id = joined.room_id
    joined_now = room_id not in client.rooms
    state = await client.room_get_state(room_id)
    problem = None
    if isinstance(state, nio.RoomGetStateError):
        problem = f"I could not read {ref}: {state.message}"
    elif (_content(state.events, "m.room.create") or {}).get("type") != "m.space":
        problem = f"{ref} is not a space."
    if problem is not None:
        if joined_now:
            await client.room_leave(room_id)
        raise SpaceError(problem)
    events = state.events
    children = {
        event["state_key"]
        for event in events
        if event.get("type") == "m.space.child" and event.get("content", {}).get("via")
    }
    power_levels = _content(events, "m.room.power_levels")
    creators = creators_of(_event(events, "m.room.create"))
    return SpaceCheck(
        room_id=room_id,
        joined_now=joined_now,
        lists_chat=chat_room_id in children,
        user_may_change_avatar=may_change_avatar(power_levels, sender, creators),
        bot_may_change_avatar=may_change_avatar(power_levels, client.user_id, creators),
    )


@dataclass
class AvatarState:
    """What the bot needs to know before it changes a room's avatar."""

    may_change: bool
    """Whether the bot may change it."""
    url: str | None
    """The avatar the room has now, ``None`` if it has none."""


async def read_avatar_state(client: nio.AsyncClient, room_id: str) -> AvatarState:
    """Ask the homeserver whether the bot may change the avatar of
    ``room_id`` and what it is now.

    Used for a space instead of what ``client.rooms`` knows: after the
    bot is started again, the homeserver may still list a space it has
    joined as an invitation, so ``nio`` does not hold it as a joined room.

    Raises :py:exc:`~matrix_jitsi_bot.space.SpaceError` if the state
    cannot be read.
    """
    import nio

    state = await client.room_get_state(room_id)
    if isinstance(state, nio.RoomGetStateError):
        raise SpaceError(f"I could not read {room_id}: {state.message}")
    events = state.events
    creators = creators_of(_event(events, "m.room.create"))
    return AvatarState(
        may_change=may_change_avatar(
            _content(events, "m.room.power_levels"), client.user_id, creators
        ),
        url=(_content(events, AVATAR_EVENT) or {}).get("url"),
    )


def _joined_room_id(client: nio.AsyncClient, ref: str) -> str | None:
    """The room ID of the joined room ``ref`` - an ID or an alias - or
    ``None`` if the bot is not in it.
    """
    if ref in client.rooms:
        return ref
    for room_id, room in client.rooms.items():
        if room.canonical_alias == ref:
            return room_id
    return None
