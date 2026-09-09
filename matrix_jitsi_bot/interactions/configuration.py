"""Room configuration commands: listing and changing settings a Moderator controls.

See the README's behaviour table for the commands this implements.
"""

from __future__ import annotations

from .base import BotInteraction, Mention

#: Languages the bot can be switched to. Extend as translations are added.
SUPPORTED_LANGUAGES = ["en"]


class ConfigurationInteraction(BotInteraction):
    """Lets a room's Moderators view and change the bot's settings for it."""

    @Mention(r"list languages$")
    def react_to_list_languages(self) -> str:
        return ", ".join(SUPPORTED_LANGUAGES)

    @Mention(r"set language to (?P<language>\S+)$")
    def react_to_set_language(self, language: str) -> str:
        room = self.conversation.room
        if not room.is_moderator(self.message.sender):
            return "Sorry, only room moderators can change my settings."
        if language not in SUPPORTED_LANGUAGES:
            available = ", ".join(SUPPORTED_LANGUAGES)
            return f"I don't speak {language!r}. Try one of: {available}"
        room.language = language
        room.save(update_fields=["language"])
        return f"Language set to {language}."
