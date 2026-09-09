"""Fallback reply listing every command, for when nothing else understood
what was said - and an explicit "help" command that always shows it.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from django.utils import timezone

from .base import BotInteraction, Mention

if TYPE_CHECKING:
    from matrix_jitsi_bot.db.models import CommandReply

#: Tried before `_LAST`'s catch-all, so an explicit "help" always gets
#: the full listing - see `HelpInteraction.react_to_help`.
_HELP = 9_999
#: High enough that every other interaction's reactions sort before this
#: one - it should only ever be tried once nothing else has matched.
_LAST = 10_000

_DOCS_URL = "https://matrix-jitsi-bot.readthedocs.io"
_REPO_URL = "https://github.com/niccokunzmann/matrix-jitsi-bot"

#: How long after a full command listing was last sent to a room before
#: another mistyped command earns a fresh one, rather than just a short
#: reminder - see `HelpInteraction.react_to_anything_else`.
_HELP_REMINDER_COOLDOWN = timedelta(hours=1)


def _command_listing(interaction: BotInteraction) -> str:
    """Every command ``interaction``'s current sender is allowed to
    use, plus a pointer to the full documentation and source code.

    A plain function, not a method on
    :py:class:`~matrix_jitsi_bot.interactions.help.HelpInteraction`:
    once composed into
    :py:class:`~matrix_jitsi_bot.interactions.all.AllInteractions` (see
    :py:class:`~matrix_jitsi_bot.bot.MatrixJitsiBot`), a reaction's
    wrapped method runs with whichever interaction is actually
    dispatching as ``self`` - not necessarily a
    :py:class:`~matrix_jitsi_bot.interactions.help.HelpInteraction` - so
    a ``self._command_listing()`` call would fail with an
    :py:exc:`AttributeError` there, same as the bug
    :py:func:`~matrix_jitsi_bot.db.models.jitsi._track`'s docstring
    describes.
    """
    sections = [
        reaction.help_text
        for reaction in interaction.reactions
        if reaction.allowed(interaction) and reaction.help_text
    ]
    commands = "\n\n".join(sections)
    return (
        f"{commands}\n\n"
        f"See {_DOCS_URL} for the full documentation, or "
        f"{_REPO_URL} for the source code."
    )


class HelpInteraction(BotInteraction):
    """Replies with every command the sender is allowed to use, either
    on an explicit "help", or as a fallback for something none of the
    other reactions matched.

    Composed into
    :py:class:`~matrix_jitsi_bot.interactions.all.AllInteractions` and
    registered last - see
    :py:meth:`~matrix_jitsi_bot.interactions.base.BotInteraction.add_interaction`
    - so every other reaction gets a chance to handle the message
    first.

    Their command listing is built by
    :py:func:`~matrix_jitsi_bot.interactions.help._command_listing`, a
    plain function rather than a method - see its own docstring for
    why.
    """

    title = "Help"

    @Mention(
        _HELP,
        r"help$",
        "Show what the bot understands.",
        ["help - lists every command"],
    )
    def react_to_help(self) -> str:
        """List every command the sender is allowed to use.

        Unlike
        :py:meth:`~matrix_jitsi_bot.interactions.help.HelpInteraction.react_to_anything_else`,
        an explicit "help" always gets the full listing, regardless of
        the cooldown that shortens *that* one's reply to a repeated
        mistyped command - asking outright is never treated as noise.
        It also resets the cooldown, same as sending the full listing
        there does.
        """
        room = self.conversation.room
        room.last_help_at = timezone.now()
        room.save(update_fields=["last_help_at"])
        return f"Here's what I can do:\n\n{_command_listing(self)}"

    @Mention(_LAST, r".*", "", [])
    def react_to_anything_else(self) -> CommandReply:
        """When nothing else understood, react ❌ (per the spec: "when
        a command cannot be executed, an X emoji is added" - equally
        true of one that's simply not understood at all) and reply.

        The reply is the full command listing the first time this
        happens to a room, or after
        :py:data:`~matrix_jitsi_bot.interactions.help._HELP_REMINDER_COOLDOWN`
        has passed since the last one -
        :py:attr:`~matrix_jitsi_bot.db.models.room.Room.last_help_at`
        tracks that. Otherwise, just a short reminder that "help" shows
        the listing - repeating the full wall of text for every typo in
        a busy room would be spammy.
        """
        from matrix_jitsi_bot.db.models import CommandReply

        room = self.conversation.room
        now = timezone.now()
        if (
            room.last_help_at is not None
            and now - room.last_help_at < _HELP_REMINDER_COOLDOWN
        ):
            return CommandReply(
                text=(
                    'Sorry, I don\'t understand that. Say "help" to see what I can do.'
                ),
                reaction="❌",
            )
        room.last_help_at = now
        room.save(update_fields=["last_help_at"])
        return CommandReply(
            text=(
                "Sorry, I don't understand. Here's what I can do:\n\n"
                f"{_command_listing(self)}"
            ),
            reaction="❌",
        )
