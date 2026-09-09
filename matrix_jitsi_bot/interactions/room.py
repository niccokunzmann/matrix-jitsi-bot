"""Room-level management: pausing/unpausing tracking, and leaving.

See :doc:`/using-a-bot/index` for the commands this implements.
"""

from __future__ import annotations

import re

from .base import BotInteraction, Config, Mention, Skipped

#: Lower than every other interaction's reactions (the default
#: :py:class:`~matrix_jitsi_bot.interactions.base.Mention` id starts at
#: 1) - a paused room must intercept everything except unpausing before
#: anything else gets a chance to run.
_PAUSE_CHECK = -1000
_UNPAUSE = 1
_PAUSE = 2
_LEAVE = 3

_UNPAUSE_PATTERN = re.compile(r"unpause(?: tracking)?$", re.IGNORECASE)


class RoomInteraction(BotInteraction):
    """Lets a room's Moderators pause tracking, or make the bot leave."""

    title = "Room management"

    @Mention(_PAUSE_CHECK, r"(?P<rest>.*)")
    def react_while_paused(self, rest: str) -> str | Skipped:
        """Block every command except unpausing while the room is paused.

        Registered with the lowest ``id`` of any reaction, so it always
        runs first - before deciding a paused room ignores something,
        an actual "unpause" still needs its own reaction (below,
        :py:meth:`~matrix_jitsi_bot.interactions.room.RoomInteraction.react_to_unpause`)
        to run.
        """
        room = self.conversation.room
        if not room.paused or _UNPAUSE_PATTERN.match(rest.strip()):
            return Skipped()
        return (
            "This room is paused - tracking is off, but its configuration "
            'is kept. Say "unpause tracking" to resume.'
        )

    @Config(
        _UNPAUSE,
        r"unpause(?: tracking)?$",
        "Resume tracking after a pause (moderators only).",
        ["unpause tracking - resumes tracking"],
    )
    def react_to_unpause(self) -> str:
        """Resume tracking after a pause, keeping the room's configuration."""
        room = self.conversation.room
        if not room.paused:
            return "Tracking isn't paused."
        room.paused = False
        room.save(update_fields=["paused"])
        return "Tracking resumed."

    @Config(
        _PAUSE,
        r"pause(?: tracking)?$",
        "Pause tracking without losing the configuration (moderators only).",
        ["pause tracking - stops tracking, keeps the configuration"],
    )
    def react_to_pause(self) -> str:
        """Pause tracking without losing the room's configuration.

        :py:meth:`~matrix_jitsi_bot.interactions.room.RoomInteraction.react_while_paused`
        (run first, unconditionally, while paused) already intercepts
        this if the room is already paused - reaching here means it
        wasn't.
        """
        room = self.conversation.room
        room.paused = True
        room.save(update_fields=["paused"])
        return "Tracking paused."

    @Config(
        _LEAVE,
        r"leave$",
        "Make the bot leave this room and forget it (moderators only).",
        ["leave - the bot leaves and forgets this room"],
    )
    def react_to_leave(self) -> str:
        """Flag the room to actually be left once this reply is sent.

        Leaving is a Matrix API call on the live client, which isn't
        reachable from here - ``bot.py`` checks
        :py:attr:`~matrix_jitsi_bot.db.models.room.Room.should_leave`
        after sending this reply, calls the API, then deletes the
        :py:class:`~matrix_jitsi_bot.db.models.room.Room` row (which
        would otherwise cascade-delete this very reply first).
        """
        room = self.conversation.room
        room.should_leave = True
        room.save(update_fields=["should_leave"])
        return "Leaving this room now. Goodbye!"
