"""Showing that a conference is active on the room's avatar.

See :doc:`/using-a-bot/track-a-conference` for the commands, and
:py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.update_speaker_avatars`
for what happens to the avatar.
"""

from __future__ import annotations

from .base import BotInteraction, CommandError, Config
from .jitsi import _ROOM, _track, _untrack

_CHANGE_AVATAR = 206
_KEEP_AVATAR = 207


class AvatarInteraction(BotInteraction):
    """Lets a room's Moderators show a speaker on the room's avatar while
    a tracked conference is active.
    """

    title = "Change the room avatar while a conference is active"

    @Config(
        _CHANGE_AVATAR,
        rf"change avatar when{_ROOM} is active$",
        (
            "Change this room's avatar - a speaker is shown on it - while a tracked "
            "conference is active, and restore the avatar afterwards "
            "(moderators only, and the bot must be allowed to change "
            "the room's avatar). The room can be a URL, or a hostname "
            "or short name shortcut."
        ),
        [
            "change avatar when https://meet.example.com/Room is active",
            "change avatar when Room is active - using the short name shortcut",
        ],
    )
    def react_to_change_avatar(self, room: str | None = None) -> str:
        """Show a speaker on the room's avatar while ``room`` is open -
        see
        :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.update_speaker_avatars`.

        Refused with a
        :py:exc:`~matrix_jitsi_bot.interactions.base.CommandError` if
        the bot may not change the room's avatar, see
        :py:attr:`~matrix_jitsi_bot.interactions.base.BotInteraction.can_set_avatar`.
        """
        if not self.can_set_avatar:
            raise CommandError(
                "I am not allowed to change this room's avatar. Give me a "
                "power level that allows it, then ask again."
            )
        reply = _track(self.conversation, room, ("show_speaker",))
        return f"{reply} A speaker is shown on the room's avatar while it is active."

    @Config(
        _KEEP_AVATAR,
        rf"(?:don'?t|do not) change avatar when{_ROOM} is active$",
        "Stop changing this room's avatar for a conference (moderators only).",
        ["don't change avatar when Room is active"],
    )
    def react_to_keep_avatar(self, room: str | None = None) -> str:
        """Undo
        :py:meth:`~matrix_jitsi_bot.interactions.avatar.AvatarInteraction.react_to_change_avatar`;
        the original avatar comes back within moments.
        """
        return _untrack(self.conversation, room, ("show_speaker",))
