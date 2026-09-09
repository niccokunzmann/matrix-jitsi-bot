"""Framework and built-in reactions for the bot's chat-room interactions.

See `.base` for how to declare a `BotInteraction`. Concrete, pluggable
interactions live alongside it as their own modules in this package.
"""

from .base import BotInteraction, Mention, MessageReaction
from .configuration import ConfigurationInteraction
from .greeting import GreetingInteraction

__all__ = [
    "BotInteraction",
    "ConfigurationInteraction",
    "GreetingInteraction",
    "Mention",
    "MessageReaction",
]
