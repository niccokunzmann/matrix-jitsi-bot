r"""Framework for defining the bot's chat-room command reactions.

Subclass `BotInteraction` and decorate methods with
`@MessageReaction(<regex>)` to react to matching messages::

    class Greeter(BotInteraction):

        @MessageReaction(r"hello (?P<name>\w+)")
        def react_to_command(self, name: str) -> CommandReply | str | None:
            return f"Hello, {name}!"

Named groups in the regex become keyword arguments of the decorated
method. Its return value controls the bot's reply:

- `None`: no reply.
- `str`: a simple text reply.
- `CommandReply`: a reply that is additionally persisted in the database,
  tied to the message it responds to.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, ClassVar

from matrix_jitsi_bot.db.models import CommandReply

if TYPE_CHECKING:
    from collections.abc import Callable

    from matrix_jitsi_bot.db.models import Conversation, Message


class MessageReaction:
    """Decorator marking a `BotInteraction` method as reacting to messages
    matching `pattern`.

    Applying it (`@MessageReaction(pattern)`) wraps the method in a
    `MessageReaction` instance holding the compiled `pattern` and the
    original function. `BotInteraction.__init__` finds these instances in
    the class's `__dict__` and calls `register` on each to build its
    handler table.

    As a descriptor, it otherwise stays transparent: accessed on an
    instance (`self.method_name`), `__get__` binds and returns the
    wrapped function, just like an ordinary method would. Accessed on
    the class itself (`Klass.method_name`) - which is what `help()` and
    Sphinx's autodoc do - it likewise returns the plain wrapped function,
    so it documents with its own docstring and signature rather than as
    an opaque `MessageReaction` object.
    """

    def __init__(
        self, pattern: str, description: str = "", examples: list[str] | None = None
    ) -> None:
        self.pattern = re.compile(f"^({pattern})$")
        self.func: Callable | None = None
        self.description = description
        self.examples = examples or []

    def __call__(self, func: Callable) -> MessageReaction:
        self.func = func
        return self

    def __get__(self, obj: object, objtype: type | None = None) -> Callable:
        if obj is None:
            return self.func
        return self.func.__get__(obj, objtype)

    def match(self, text: str) -> re.Match | None:
        """Try `pattern` against `text`. Overridden by subclasses that
        preprocess `text` first, e.g. `Mention`.
        """
        return self.pattern.match(text)

    def register(self, interaction: BotInteraction) -> None:
        """Bind this handler to `interaction` and add it to its handler table."""
        if self.func is None:
            raise ValueError(f"MessageReaction {self} has no wrapped function")

        interaction.add_reaction(self)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.pattern.pattern!r})"

    def get_message_text(self, message: Message) -> str:
        """Get the text to match against `pattern` from a `Message`.

        Overridden by subclasses that preprocess the message first, e.g.
        `Mention`.
        """
        return message.sanitized_body

    def react_to_matrix_message(
        self, conversation: Conversation
    ) -> CommandReply | None:
        message = conversation.last_message
        if message is None:
            return None

        text = self.get_message_text(message)

        match = self.match(text)
        if not match:
            return None
        if self.func is None:
            raise ValueError(f"MessageReaction {self} has no wrapped function")

        result = self.func(**match.groupdict())
        if result is None:
            return None
        if isinstance(result, str):
            return CommandReply(text=result, message=message)
        return result

    @property
    def help_text(self):
        """A short description of this command, suitable for a help message."""
        if not self.examples:
            return f"""{self.description}"""
        example_text = "\n".join(" - " + example for example in self.examples)
        return f"""{self.description}:\n{example_text}"""


class Mention(MessageReaction):
    r"""`MessageReaction` variant matching only the command text, after
    stripping an optional leading mention of the bot - "@bot:matrix.org:
    hello", "bot: hello", and plain "hello" all match a `pattern` of just
    ``r"hello$"``.

    The leading word only counts as a mention if it ends in ``:`` or
    ``,`` (or starts with ``@``, requiring no punctuation) - "hello" isn't
    mistaken for a bot named "hello" with nothing said, and "hello there"
    isn't mistaken for a mention of "hello" either. `message.sanitized_body`
    already collapses whitespace to single spaces and strips the ends, so
    finding the split point is a plain `str.split` - `pattern` doesn't need
    to account for `\s` around the mention at all.
    """

    _MENTION = re.compile(r"^@\S+$|^\S+[:,]$")

    def match(self, text: str) -> re.Match | None:
        first, _, rest = text.partition(" ")
        if self._MENTION.match(first):
            text = rest.strip()
        return self.pattern.match(text)


class BotInteraction:
    """Base class for defining the bot's chat-room reactions.

    See the module docstring for how to declare handlers with
    `@MessageReaction`.
    """

    title: ClassVar[str] = ""

    def __init__(self) -> None:
        self.conversation: Conversation | None = None
        self.message: Message | None = None
        self._reactions: list[MessageReaction] = []
        seen: set[str] = set()
        for klass in type(self).__mro__:
            for name, attr in vars(klass).items():
                if name in seen:
                    continue
                if isinstance(attr, MessageReaction):
                    seen.add(name)
                    attr.register(self)

    def add_reaction(self, reaction: MessageReaction) -> None:
        """Add a `MessageReaction` handler to this interaction.

        Called by `MessageReaction.register` during `__init__`.
        """
        self._reactions.append(reaction)

    def react_to_matrix_message(
        self, conversation: Conversation
    ) -> CommandReply | None:
        """Try every `@MessageReaction` handler against the latest message.

        `conversation` is the recorded `Conversation` for the room the
        message arrived in - the message itself, and every message
        before it, is already in the database. While handling it,
        `self.conversation` and `self.message` give handler methods
        access to the room and sender (e.g. for `room.is_moderator(...)`
        checks), without it having to be threaded through every regex.

        Returns the first non-`None` result, in declaration order. A
        `CommandReply` result is tied to the message it answers and
        saved before being returned.
        """

        for reaction in self._reactions:
            reply = reaction.react_to_matrix_message(conversation)
            if reply is not None:
                return reply
        return None

    def add_interaction(self, interaction: BotInteraction) -> None:
        """Add another `BotInteraction` to this one.

        This is for composing multiple interactions into a single
        collection, e.g. `AllInteractions`.
        """
        self._reactions.extend(interaction._reactions)
