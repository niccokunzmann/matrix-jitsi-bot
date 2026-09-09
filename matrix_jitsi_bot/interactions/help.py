"""Fallback reply listing every command, for when nothing else understood
what was said.
"""

from __future__ import annotations

from .base import BotInteraction, Mention

#: High enough that every other interaction's reactions sort before this
#: one - it should only ever be tried once nothing else has matched.
_LAST = 10_000

_DOCS_URL = "https://matrix-jitsi-bot.readthedocs.io"
_REPO_URL = "https://github.com/niccokunzmann/matrix-jitsi-bot"


class HelpInteraction(BotInteraction):
    """Replies with every command the sender is allowed to use, when
    addressed with something none of the other reactions matched.

    Composed into
    :py:class:`~matrix_jitsi_bot.interactions.all.AllInteractions` and
    registered last - see
    :py:meth:`~matrix_jitsi_bot.interactions.base.BotInteraction.add_interaction`
    - so every other reaction gets a chance to handle the message
    first.

    Its method reads ``self.reactions`` rather than storing its own
    list of interactions: once folded into
    :py:class:`~matrix_jitsi_bot.interactions.all.AllInteractions`, a
    reaction's wrapped method always runs with whichever interaction is
    actually dispatching as ``self`` - not necessarily the one it was
    declared on - and that combined interaction already has every
    reaction in ``self.reactions``.
    """

    title = "Help"

    @Mention(
        _LAST,
        r".*",
        "Show what the bot understands.",
        ["help - lists every command"],
    )
    def react_to_anything_else(self) -> str:
        """When nothing else understood, list every command the sender
        is allowed to use.
        """
        sections = [
            reaction.help_text
            for reaction in self.reactions
            if reaction.allowed(self) and reaction.help_text
        ]
        commands = "\n\n".join(sections)
        return (
            "Sorry, I don't understand. Here's what I can do:\n\n"
            f"{commands}\n\n"
            f"See {_DOCS_URL} for the full documentation, or "
            f"{_REPO_URL} for the source code."
        )
