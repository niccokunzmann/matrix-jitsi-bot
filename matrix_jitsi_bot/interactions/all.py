"""This contains all possible interactions."""

from matrix_jitsi_bot.interactions import BotInteraction
from matrix_jitsi_bot.interactions.configuration import ConfigurationInteraction
from matrix_jitsi_bot.interactions.greeting import GreetingInteraction


class AllInteractions(BotInteraction):
    """A collection of all interactions."""

    title = "Interact with the bot"

    def __init__(self) -> None:
        super().__init__()

        self.setup_interactions()
        self.add_interactions()

    def add_interactions(self) -> None:
        """Add all interactions to this collection."""
        self.add_interaction(self.greeting)
        self.add_interaction(self.configuration)

    def setup_interactions(self) -> None:
        """Create instances of all interactions."""

        self.greeting = GreetingInteraction()
        self.configuration = ConfigurationInteraction()
