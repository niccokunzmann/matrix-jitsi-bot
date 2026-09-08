"""Small talk: the bot greeting people back.

See the README's behaviour table for the commands this implements.
"""

from __future__ import annotations

from .base import PREFIX, BotInteraction, MessageReaction


class GreetingInteraction(BotInteraction):
    """Replies to a friendly greeting."""

    @MessageReaction(PREFIX + r"hello\s*$")
    def react_to_hello(self) -> str:
        return "hello"
