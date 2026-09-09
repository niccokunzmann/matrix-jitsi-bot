"""This contains all possible interactions."""

from .base import BotInteraction
from .greeting import GreetingInteraction
from .help import HelpInteraction
from .room import RoomInteraction


class AllInteractions(BotInteraction):
    """A collection of all interactions - the bot's default, see
    :py:class:`~matrix_jitsi_bot.bot.MatrixJitsiBot`.
    """

    title = "Interact with the bot"

    def __init__(self) -> None:
        """Build every interaction (see
        :py:meth:`~matrix_jitsi_bot.interactions.all.AllInteractions.setup_interactions`)
        and fold their reactions into this one's.
        """
        super().__init__()

        self.setup_interactions()
        self.add_interactions()

    def add_interactions(self) -> None:
        """Add all interactions to this collection.

        ``self.help`` is added last, so every other interaction's
        reactions get a chance to match first - see
        :py:class:`~matrix_jitsi_bot.interactions.help.HelpInteraction`.
        """
        self.add_interaction(self.room)
        self.add_interaction(self.greeting)
        self.add_interaction(self.jitsi)
        self.add_interaction(self.help)

    def setup_interactions(self) -> None:
        """Create instances of all interactions.

        :py:class:`~matrix_jitsi_bot.db.models.jitsi.JitsiInteraction`
        is imported here, not at module level: it lives in
        :py:mod:`matrix_jitsi_bot.db.models.jitsi`, which itself
        imports from ``.base`` - importing it eagerly here would form a
        circular import (see :py:mod:`matrix_jitsi_bot.interactions`'s
        docstring for the full cycle).
        """
        from matrix_jitsi_bot.db.models import JitsiInteraction

        self.room = RoomInteraction()
        self.greeting = GreetingInteraction()
        self.jitsi = JitsiInteraction()
        self.help = HelpInteraction()
