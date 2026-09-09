"""Fallback reply for when nothing else understood what was said - and
an explicit "help" command that lists everything the bot can do.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

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

#: `HelpInteraction.react_to_anything_else`'s reply to an unrecognized
#: command - short and constant, never the full listing, so a busy room
#: with several typos in a row isn't spammed with it - see
#: `HelpInteraction.react_to_help` for that.
_NOT_UNDERSTOOD = (
    'Sorry, I don\'t understand that command. Say "help" to see what I can do.'
)


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
    """An explicit "help" lists every command the sender is allowed to
    use; anything else unrecognized gets a short ❌ reminder instead -
    see
    :py:meth:`~matrix_jitsi_bot.interactions.help.HelpInteraction.react_to_help`
    and
    :py:meth:`~matrix_jitsi_bot.interactions.help.HelpInteraction.react_to_anything_else`.

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

        The only way to get the full listing - a mistyped/unrecognized
        command never triggers it automatically, see
        :py:meth:`~matrix_jitsi_bot.interactions.help.HelpInteraction.react_to_anything_else`.
        """
        return f"Here's what I can do:\n\n{_command_listing(self)}"

    @Mention(_LAST, r".*", "", [])
    def react_to_anything_else(self) -> CommandReply:
        """When nothing else understood, react ❌ (per the spec: "when
        a command cannot be executed, an X emoji is added" - equally
        true of one that's simply not understood at all) and reply
        with a short, constant reminder to say "help" - never the full
        listing, which would spam a busy room with the same wall of
        text for every typo; see
        :py:meth:`~matrix_jitsi_bot.interactions.help.HelpInteraction.react_to_help`
        for that instead.
        """
        from matrix_jitsi_bot.db.models import CommandReply

        return CommandReply(text=_NOT_UNDERSTOOD, reaction="❌")
