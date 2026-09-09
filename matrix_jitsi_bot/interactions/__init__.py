"""Framework and built-in reactions for the bot's chat-room interactions.

See :py:mod:`matrix_jitsi_bot.interactions.base` for how to declare a
:py:class:`~matrix_jitsi_bot.interactions.base.BotInteraction`.
Concrete, pluggable interactions live alongside it as their own
modules in this package - except
:py:class:`~matrix_jitsi_bot.db.models.jitsi.JitsiInteraction`, which
lives with the Jitsi models it works with, in
:py:mod:`matrix_jitsi_bot.db.models.jitsi`, and is deliberately not
re-exported here: that module itself imports from
:py:mod:`matrix_jitsi_bot.interactions.base`, so an eager
``from matrix_jitsi_bot.db.models import JitsiInteraction`` at the top
of this file would be circular. Import it from
:py:mod:`matrix_jitsi_bot.db.models` directly instead.
"""

from .all import AllInteractions
from .base import BotInteraction, Config, Mention, MessageReaction, Skipped
from .greeting import GreetingInteraction
from .help import HelpInteraction
from .room import RoomInteraction

__all__ = [
    "AllInteractions",
    "BotInteraction",
    "Config",
    "GreetingInteraction",
    "HelpInteraction",
    "Mention",
    "MessageReaction",
    "RoomInteraction",
    "Skipped",
]
