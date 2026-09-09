"""Small talk: the bot greeting people back.

See the README's behaviour table for the commands this implements.
"""

from __future__ import annotations

from .base import BotInteraction, Mention


class GreetingInteraction(BotInteraction):
    """Replies to a friendly greeting."""

    title = "Greet the bot"

    @Mention(r"[Hh]ello[!.]?")
    def react_to_hello(self) -> str:
        return "Hello!"
