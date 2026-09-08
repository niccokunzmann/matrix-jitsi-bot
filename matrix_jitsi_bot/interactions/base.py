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
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from matrix_jitsi_bot.db.models import CommandReply, Conversation, Message

#: An optional leading mention/name before the actual command, e.g.
#: "@bot:matrix.org: hello" or just "hello". Interaction modules prefix
#: their `MessageReaction` patterns with this.
PREFIX = r"^(?:@?\S+[:,]?\s+)?"


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

    def __init__(self, pattern: str) -> None:
        self.pattern = re.compile(pattern)
        self.func: Callable | None = None

    def __call__(self, func: Callable) -> MessageReaction:
        self.func = func
        return self

    def __get__(self, obj: object, objtype: type | None = None) -> Callable:
        if obj is None:
            return self.func
        return self.func.__get__(obj, objtype)

    def register(self, interaction: BotInteraction) -> None:
        """Bind this handler to `interaction` and add it to its handler table."""
        bound = self.func.__get__(interaction, type(interaction))
        interaction._handlers.append((self.pattern, bound))  # noqa: SLF001

    def __repr__(self) -> str:
        return f"MessageReaction({self.pattern.pattern!r})"


class BotInteraction:
    """Base class for defining the bot's chat-room reactions.

    See the module docstring for how to declare handlers with
    `@MessageReaction`.
    """

    def __init__(self) -> None:
        self.conversation: Conversation | None = None
        self.message: Message | None = None
        self._handlers: list[tuple[re.Pattern, Callable]] = []
        seen: set[str] = set()
        for klass in type(self).__mro__:
            for name, attr in vars(klass).items():
                if name in seen:
                    continue
                if isinstance(attr, MessageReaction):
                    seen.add(name)
                    attr.register(self)

    def react_to_matrix_message(
        self, conversation: Conversation
    ) -> CommandReply | str | None:
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
        from matrix_jitsi_bot.db.models import CommandReply

        message = conversation.messages.last()
        if message is None:
            raise ValueError(f"{conversation!r} has no recorded messages")

        self.conversation = conversation
        self.message = message
        text = message.sanitized_body

        for pattern, method in self._handlers:
            match = pattern.match(text)
            if not match:
                continue
            result = method(**match.groupdict())
            if result is None:
                continue
            if isinstance(result, CommandReply):
                result.message = message
                result.save()
            return result
        return None
