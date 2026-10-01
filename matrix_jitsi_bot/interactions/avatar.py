"""Showing that a conference is active on an avatar - of the chat, or
of a space that lists the chat.

See :doc:`/using-a-bot/track-a-conference` for the commands, and
:py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.update_speaker_avatars`
for what happens to the avatar.

The helpers are plain functions, not methods: once composed into
:py:class:`~matrix_jitsi_bot.interactions.all.AllInteractions`, a
reaction's wrapped method runs with whichever interaction is actually
dispatching as ``self`` - see
:py:func:`~matrix_jitsi_bot.interactions.jitsi._track`.
"""

from __future__ import annotations

from matrix_jitsi_bot.db.models import Space, TrackedJitsiRoom
from matrix_jitsi_bot.space import SpaceError, inspect_space

from .base import BotInteraction, CommandError, Config
from .jitsi import _ROOM, _resolve_tracked_room, _track, _untrack

_CHANGE_AVATAR = 206
_KEEP_AVATAR = 207

#: What the avatar of a chat is called in a command, as opposed to a
#: space: a room alias or room ID.
_THIS_CHAT = ("this chat", "this room")
_TARGET = r"(?: of (?P<target>this chat|this room|[#!]\S+))?"


def _leave_if_unused(interaction: BotInteraction, room_id: str) -> None:
    """Leave the space ``room_id`` unless a chat is set up to change its
    avatar - or it still shows the speaker, which is restored first.
    """
    from asgiref.sync import async_to_sync

    space = Space.objects.filter(room_id=room_id).first()
    if space is not None and (space.is_used() or space.speaker_shown):
        return
    async_to_sync(interaction.matrix_client.room_leave)(room_id)


def _change_space_avatar(
    interaction: BotInteraction, target: str, ref: str | None
) -> str:
    """Set up the chat to change the avatar of the space ``target`` while
    the conference ``ref`` is open.

    The bot joins the space if it must, and checks that the space lists
    this chat, that the sender may change the space's avatar themselves
    and that the bot may. If not, it says so. A space that does not list
    this chat is left again, unless it is used already - the others
    stay, so that the bot does not need to be invited once more when the
    power is given.
    """
    from asgiref.sync import async_to_sync

    from matrix_jitsi_bot.db.models import Account

    client = interaction.matrix_client
    if client is None:
        raise CommandError("I cannot look at a space right now.")
    chat = interaction.conversation.room
    try:
        check = async_to_sync(inspect_space)(
            client, target, chat.room_id, interaction.message.sender
        )
    except SpaceError as exc:
        raise CommandError(str(exc)) from exc

    problem = None
    if not check.lists_chat:
        problem = (
            f"{target} does not list this chat as one of its rooms, so I do "
            "not change its avatar and have left the space. Add this chat to "
            "the space, then ask again."
        )
        _leave_if_unused(interaction, check.room_id)
    elif not check.user_may_change_avatar:
        problem = (
            f"You are not allowed to change the avatar of {target} yourself, "
            "so I do not change it for you."
        )
    elif not check.bot_may_change_avatar:
        problem = (
            f"I am not allowed to change the avatar of {target}. Give me a "
            "power level that allows it - in most spaces that is being a "
            "moderator - then ask again."
        )
    if problem is not None:
        raise CommandError(problem)

    _track(interaction.conversation, ref, ())
    jitsi_room = _resolve_tracked_room(chat, ref)
    space, _ = Space.objects.get_or_create(
        room_id=check.room_id,
        defaults={
            "account": Account.objects.filter(user_id=client.user_id).first(),
        },
    )
    if target.startswith("#") and space.alias != target:
        space.alias = target
        space.save(update_fields=["alias"])
    TrackedJitsiRoom.objects.get(room=chat, jitsi_room=jitsi_room).avatar_spaces.add(
        space
    )
    return (
        f"Now tracking {jitsi_room.url}. A speaker is shown on the avatar of "
        f"{target} while it is active."
    )


def _keep_space_avatar(
    interaction: BotInteraction, target: str, ref: str | None
) -> str:
    """Stop changing the avatar of the space ``target`` for ``ref``."""
    from django.db.models import Q

    chat = interaction.conversation.room
    jitsi_room = _resolve_tracked_room(chat, ref)
    tracked = TrackedJitsiRoom.objects.get(room=chat, jitsi_room=jitsi_room)
    space = tracked.avatar_spaces.filter(Q(alias=target) | Q(room_id=target)).first()
    if space is None:
        raise CommandError(
            f"I do not change the avatar of {target} for {jitsi_room.url}."
        )
    tracked.avatar_spaces.remove(space)
    if not tracked.is_tracking_anything():
        tracked.delete()
    return f"I no longer change the avatar of {target} for {jitsi_room.url}."


class AvatarInteraction(BotInteraction):
    """Lets a room's Moderators show a speaker on the avatar of the room,
    or of a space that lists it, while a tracked conference is active.
    """

    title = "Change an avatar while a conference is active"

    @Config(
        _CHANGE_AVATAR,
        rf"change avatar{_TARGET} when{_ROOM} is active$",
        (
            "Change the avatar - a speaker is shown on it - while a tracked "
            "conference is active, and restore it afterwards (moderators "
            "only, and the bot must be allowed to change the avatar). It is "
            "the avatar of this chat, or of a space that lists this chat - "
            "then you must be allowed to change the space's avatar too, and "
            "the bot joins the space if it is not in it. The conference can "
            "be a URL, or a hostname or short name shortcut."
        ),
        [
            "change avatar when https://meet.example.com/Room is active",
            "change avatar when Room is active - using the short name shortcut",
            "change avatar of this chat when Room is active - the same, explicit",
            "change avatar of this room when Room is active - the same",
            "change avatar of #space:example.org when Room is active"
            " - the avatar of a space",
        ],
    )
    def react_to_change_avatar(
        self, target: str | None = None, room: str | None = None
    ) -> str:
        """Show a speaker on the avatar of this chat - ``target`` is
        omitted or says "this chat" or "this room" - or of the space
        ``target``, while the conference ``room`` is open - see
        :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.update_speaker_avatars`.

        Refused with a
        :py:exc:`~matrix_jitsi_bot.interactions.base.CommandError` if
        the bot may not change the avatar, see
        :py:attr:`~matrix_jitsi_bot.interactions.base.BotInteraction.can_set_avatar`
        and :py:func:`~matrix_jitsi_bot.interactions.avatar._change_space_avatar`.
        """
        if target is not None and target not in _THIS_CHAT:
            return _change_space_avatar(self, target, room)
        if not self.can_set_avatar:
            raise CommandError(
                "I am not allowed to change this room's avatar. Give me a "
                "power level that allows it - in most rooms that is being a "
                "moderator - then ask again."
            )
        reply = _track(self.conversation, room, ("show_speaker",))
        return f"{reply} A speaker is shown on the room's avatar while it is active."

    @Config(
        _KEEP_AVATAR,
        rf"(?:don'?t|do not) change avatar{_TARGET} when{_ROOM} is active$",
        "Stop changing an avatar for a conference (moderators only).",
        [
            "don't change avatar when Room is active",
            "don't change avatar of #space:example.org when Room is active",
        ],
    )
    def react_to_keep_avatar(
        self, target: str | None = None, room: str | None = None
    ) -> str:
        """Undo
        :py:meth:`~matrix_jitsi_bot.interactions.avatar.AvatarInteraction.react_to_change_avatar`;
        the original avatar comes back within moments.
        """
        if target is not None and target not in _THIS_CHAT:
            return _keep_space_avatar(self, target, room)
        return _untrack(self.conversation, room, ("show_speaker",))
