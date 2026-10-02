"""Framework and built-in reactions for the bot's chat-room interactions.

See :py:mod:`matrix_jitsi_bot.interactions.base` for how to declare a
:py:class:`~matrix_jitsi_bot.interactions.base.BotInteraction`.
Concrete, pluggable interactions live alongside it as their own
modules in this package.
"""

from .all import AllInteractions
from .avatar import AvatarInteraction
from .base import BotInteraction, Config, Mention, MessageReaction, Skipped
from .chat_notification import ChatNotificationInteraction
from .greeting import GreetingInteraction
from .help import HelpInteraction
from .room import RoomInteraction
from .status_message import StatusMessageInteraction

__all__ = [
    "AllInteractions",
    "AvatarInteraction",
    "BotInteraction",
    "ChatNotificationInteraction",
    "Config",
    "GreetingInteraction",
    "HelpInteraction",
    "Mention",
    "MessageReaction",
    "RoomInteraction",
    "Skipped",
    "StatusMessageInteraction",
]
