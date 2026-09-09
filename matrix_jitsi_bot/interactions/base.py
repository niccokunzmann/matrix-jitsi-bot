r"""Framework for defining the bot's chat-room command reactions.

Subclass :py:class:`~matrix_jitsi_bot.interactions.base.BotInteraction`
and decorate methods with
:py:class:`~matrix_jitsi_bot.interactions.base.Mention` ``(<id>,
<regex>)`` to react to messages addressed to the bot::

    class Greeter(BotInteraction):

        @Mention(1, r"hello (?P<name>\w+)", "Say hello.", ["hello Alice - greets"])
        def react_to_command(self, name: str) -> CommandReply | str | None:
            return f"Hello, {name}!"

Named groups in the regex become keyword arguments of the decorated
method. Its return value controls the bot's reply:

- ``None`` or a returned
  :py:class:`~matrix_jitsi_bot.interactions.base.Skipped` instance: no
  reply - try the next reaction, in ascending ``id`` order.
- ``str``: a simple text reply, saved as a
  :py:class:`~matrix_jitsi_bot.db.models.conversation.CommandReply` and
  ending the search.
- :py:class:`~matrix_jitsi_bot.db.models.conversation.CommandReply`:
  likewise, but with more control over the reply (e.g. ``html``), also
  ending the search.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from collections.abc import Callable

    import nio
    import niobot

    from matrix_jitsi_bot.db.models import CommandReply, Conversation, Message

logger = logging.getLogger(__name__)


class Skipped:
    """Returned by a
    :py:class:`~matrix_jitsi_bot.interactions.base.MessageReaction`
    handler to defer to the next matching reaction, same as returning
    ``None``.

    A handler whose pattern matched but that decides the message isn't
    really its to answer can return this instead of ``None`` to say so
    explicitly, rather than leaving the reader to wonder whether "no
    reply" was deliberate.
    """

    def __repr__(self) -> str:
        """``"Skipped()"``, for debugging/logging."""
        return "Skipped()"


class CommandError(Exception):
    """Raised by a
    :py:class:`~matrix_jitsi_bot.interactions.base.Config` handler to
    signal that it failed - its message becomes the reply text, same as
    returning a plain ``str``, but
    :py:meth:`~matrix_jitsi_bot.interactions.base.MessageReaction.react_to_matrix_message`
    reacts with ❌ instead of ✅ (see that method), per the spec's
    "when a command cannot be executed, an X emoji is added". Not
    meaningful on a non-``Config`` reaction - a query like ``check`` or
    ``status`` never gets a reaction either way.
    """


class MessageReaction:
    """Decorator marking a
    :py:class:`~matrix_jitsi_bot.interactions.base.BotInteraction`
    method as reacting to messages matching ``pattern``.

    Applying it (``@MessageReaction(id, pattern)``) wraps the method in
    a :py:class:`~matrix_jitsi_bot.interactions.base.MessageReaction`
    instance holding ``id``, the compiled ``pattern``, and the original
    function.
    :py:meth:`~matrix_jitsi_bot.interactions.base.BotInteraction.__init__`
    finds these instances in the class's ``__dict__`` and calls
    :py:meth:`~matrix_jitsi_bot.interactions.base.MessageReaction.register`
    on each to build its reaction table, sorted by ``id`` - the
    deterministic order they're tried in, lowest first, regardless of
    declaration order.

    ``description`` and ``examples`` document the command for a
    catch-all help reaction to show when nothing else matches - see
    :py:attr:`~matrix_jitsi_bot.interactions.base.MessageReaction.help_text`.

    As a descriptor, it otherwise stays transparent: accessed on an
    instance (``self.method_name``),
    :py:meth:`~matrix_jitsi_bot.interactions.base.MessageReaction.__get__`
    binds and returns the wrapped function, just like an ordinary
    method would. Accessed on the class itself (``Klass.method_name``)
    - which is what ``help()`` and Sphinx's autodoc do - it likewise
    returns the plain wrapped function, so it documents with its own
    docstring and signature rather than as an opaque
    :py:class:`~matrix_jitsi_bot.interactions.base.MessageReaction`
    object.
    """

    def __init__(
        self,
        id: int,  # noqa: A002 - the natural name; ordering is its whole point
        pattern: str,
        description: str = "",
        examples: list[str] | None = None,
    ) -> None:
        """Store ``id`` (the dispatch order), the compiled ``pattern``,
        and the ``description``/``examples`` shown in help text - see
        the class docstring.
        """
        self.id = id
        self.pattern = re.compile(f"^({pattern})$")
        self.description = description
        self.examples = examples or []
        self.func: Callable | None = None

    def __call__(self, func: Callable) -> MessageReaction:
        """Store the decorated ``func`` as the wrapped handler, and
        return ``self`` in its place - this is what makes
        ``@MessageReaction(id, pattern)`` work as a decorator.
        """
        self.func = func
        return self

    def __get__(self, obj: object, objtype: type | None = None) -> Callable:
        """Descriptor protocol: return the wrapped function, bound to
        ``obj`` if accessed on an instance - see the class docstring.
        """
        if obj is None:
            return self.func
        return self.func.__get__(obj, objtype)

    def match(self, text: str) -> re.Match | None:
        """Try ``pattern`` against ``text``. Overridden by subclasses
        that preprocess ``text`` first, e.g.
        :py:class:`~matrix_jitsi_bot.interactions.base.Mention`.
        """
        return self.pattern.match(text)

    def allowed(self, interaction: BotInteraction) -> bool:
        """Whether ``interaction``'s sender may use this command at all.

        Called after
        :py:meth:`~matrix_jitsi_bot.interactions.base.MessageReaction.match`
        succeeds, before the wrapped method runs. Overridden by
        subclasses that restrict who can use them, e.g.
        :py:class:`~matrix_jitsi_bot.interactions.base.Config`
        (moderators only).
        """
        return True

    def register(self, interaction: BotInteraction) -> None:
        """Add this reaction to ``interaction``'s reaction table."""
        if self.func is None:
            raise ValueError(f"MessageReaction {self} has no wrapped function")
        interaction.add_reaction(self)

    def __repr__(self) -> str:
        """``ClassName(id, pattern)``, for debugging/logging."""
        return f"{type(self).__name__}({self.id!r}, {self.pattern.pattern!r})"

    def get_message_text(self, message: Message) -> str:
        """Get the text to match against ``pattern`` from a ``message``.

        Overridden by subclasses that preprocess the message first,
        e.g. :py:class:`~matrix_jitsi_bot.interactions.base.Mention`.
        """
        return message.sanitized_body

    @property
    def help_text(self) -> str:
        """A short description of this command, suitable for a help message."""
        if not self.examples:
            return self.description
        example_text = "\n".join(f"- {example}" for example in self.examples)
        return f"{self.description}\n{example_text}"

    def react_to_matrix_message(
        self, interaction: BotInteraction, conversation: Conversation
    ) -> CommandReply | None:
        """Try this reaction against ``conversation``'s latest message,
        on behalf of ``interaction`` (the
        :py:class:`~matrix_jitsi_bot.interactions.base.BotInteraction`
        whose method this wraps - not necessarily the one this reaction
        was declared on, e.g. when composed into
        :py:class:`~matrix_jitsi_bot.interactions.all.AllInteractions`).

        A :py:class:`~matrix_jitsi_bot.interactions.base.Config`
        reaction also gets a ✅/❌ reaction on the triggering message:
        ✅ unless denied for not being a moderator, or the handler
        raised :py:exc:`~matrix_jitsi_bot.interactions.base.CommandError`
        (❌, both times) - see that exception.
        """
        from matrix_jitsi_bot.db.models import CommandReply

        message = conversation.last_message
        if message is None:
            return None

        text = self.get_message_text(message)
        match = self.match(text)
        if match is None:
            return None

        failed = False
        if not self.allowed(interaction):
            result = "Sorry, only room moderators can do that."
            failed = True
        else:
            if self.func is None:
                raise ValueError(f"MessageReaction {self} has no wrapped function")
            try:
                result = self.func(interaction, **match.groupdict())
            except CommandError as exc:
                result = str(exc)
                failed = True

        if result is None or isinstance(result, Skipped):
            return None
        if isinstance(result, str):
            result = CommandReply(text=result, message=message)
        if isinstance(self, Config):
            result.reaction = "❌" if failed else "✅"
        # Saved here, before `bot.py` sends it, so a `CommandReply` always
        # exists in the database (sent=False) even if sending it fails.
        result.message = message
        result.save()
        return result


class Mention(MessageReaction):
    r"""
    :py:class:`~matrix_jitsi_bot.interactions.base.MessageReaction`
    variant matching only messages addressed to the bot -
    "@bot:matrix.org: hello" or "bot: hello" match a ``pattern`` of just
    ``r"hello$"``; plain "hello" does not.

    The leading word only counts as a mention if it ends in ``:`` or
    ``,`` (or starts with ``@``, requiring no punctuation). Messages not
    addressed to the bot at all don't match - the bot only reacts when
    it's mentioned first.
    :py:attr:`~matrix_jitsi_bot.db.models.conversation.Message.sanitized_body`
    already collapses whitespace to single spaces and strips the ends,
    so finding the split point is a plain ``str.partition`` -
    ``pattern`` doesn't need to account for ``\s`` around the mention
    at all.
    """

    _MENTION = re.compile(r"^@\S+$|^\S+[:,]$")

    def match(self, text: str) -> re.Match | None:
        """Match ``pattern`` against ``text`` only if its first word is
        a mention of the bot - see the class docstring.
        """
        first, _, rest = text.partition(" ")
        if not self._MENTION.match(first):
            return None
        return self.pattern.match(rest.strip())


class Config(Mention):
    """:py:class:`~matrix_jitsi_bot.interactions.base.Mention` variant
    usable only by room Moderators - e.g. anything that changes the
    bot's settings for a room, as opposed to a query anyone may make
    (see :py:class:`~matrix_jitsi_bot.interactions.base.Mention`).
    """

    def allowed(self, interaction: BotInteraction) -> bool:
        """Whether ``interaction``'s sender is a Moderator in its room.

        If not, and ``interaction.refresh_members`` is set (see
        :py:meth:`~matrix_jitsi_bot.interactions.base.BotInteraction.__init__`),
        refreshes room membership from the live Matrix client and
        checks again - the bot's own record of who's a moderator is
        only ever as fresh as the last membership event it happened to
        receive, and a sender who was *just* promoted shouldn't be
        turned away on a stale ``no``.
        """
        room = interaction.conversation.room
        sender = interaction.message.sender
        if room.is_moderator(sender):
            return True
        if interaction.refresh_members is not None:
            interaction.refresh_members()
        return room.is_moderator(sender)


class BotInteraction:
    """Base class for defining the bot's chat-room reactions.

    See the module docstring for how to declare handlers with
    ``@Mention``/``@Config``.
    """

    #: A short, human-readable name for this interaction, e.g. for a help
    #: message to group its commands under. Set by subclasses.
    title: ClassVar[str] = ""

    def __init__(self) -> None:
        """Collect every
        :py:class:`~matrix_jitsi_bot.interactions.base.MessageReaction`
        declared on this class (or inherited), into
        :py:attr:`~matrix_jitsi_bot.interactions.base.BotInteraction.reactions`,
        sorted by ``id``.
        """
        self.conversation: Conversation | None = None
        self.message: Message | None = None
        #: A no-argument callable that refreshes this room's
        #: membership from the live Matrix client, or `None` if there
        #: isn't one available (e.g. not dispatched from
        #: `matrix_jitsi_bot.bot`) - set by the caller of
        #: `react_to_matrix_message` before each message, and consulted
        #: by `Config.allowed` on a moderator check that would
        #: otherwise fail.
        self.refresh_members: Callable[[], None] | None = None
        self.reactions: list[MessageReaction] = []
        seen: set[str] = set()
        for klass in type(self).__mro__:
            for name, attr in vars(klass).items():
                if name in seen:
                    continue
                if isinstance(attr, MessageReaction):
                    seen.add(name)
                    attr.register(self)
        self.reactions.sort(key=lambda reaction: reaction.id)

    def add_reaction(self, reaction: MessageReaction) -> None:
        """Add a
        :py:class:`~matrix_jitsi_bot.interactions.base.MessageReaction`
        to this interaction's reaction table.

        Called by
        :py:meth:`~matrix_jitsi_bot.interactions.base.MessageReaction.register`
        while
        :py:meth:`~matrix_jitsi_bot.interactions.base.BotInteraction.__init__`
        collects its class's decorated methods - not usually called
        directly.
        """
        self.reactions.append(reaction)

    def add_interaction(self, interaction: BotInteraction) -> None:
        """Fold another
        :py:class:`~matrix_jitsi_bot.interactions.base.BotInteraction`'s
        reactions into this one's.

        Lets :py:class:`~matrix_jitsi_bot.interactions.all.AllInteractions`
        compose several interactions into a single one the bot can be
        run with - see
        :py:class:`~matrix_jitsi_bot.bot.MatrixJitsiBot`.
        """
        self.reactions.extend(interaction.reactions)
        self.reactions.sort(key=lambda reaction: reaction.id)

    def react_to_matrix_message(
        self, conversation: Conversation
    ) -> CommandReply | None:
        """Try every reaction, in ascending ``id`` order, against the
        conversation's latest message.

        ``conversation`` is the recorded
        :py:class:`~matrix_jitsi_bot.db.models.conversation.Conversation`
        for the room the message arrived in - the message itself, and
        every message before it, is already in the database. While
        handling it, ``self.conversation`` and ``self.message`` give
        handler methods access to the room and sender (e.g. for
        ``room.is_moderator(...)`` checks), without it having to be
        threaded through every regex.

        Returns the first result that isn't ``None`` or a
        :py:class:`~matrix_jitsi_bot.interactions.base.Skipped`
        instance. A
        :py:class:`~matrix_jitsi_bot.db.models.conversation.CommandReply`
        result is tied to the message it answers and saved before being
        returned.
        """
        message = conversation.last_message
        if message is None:
            raise ValueError(f"{conversation!r} has no recorded messages")

        self.conversation = conversation
        self.message = message

        for reaction in self.reactions:
            reply = reaction.react_to_matrix_message(self, conversation)
            if reply is not None:
                return reply
        return None

    async def on_matrix_message(
        self, client: niobot.NioBot, room: nio.MatrixRoom, event: nio.RoomMessageText
    ) -> None:
        """Handle one live ``event`` from ``room`` on the real
        ``client``: record it, run it past
        :py:meth:`~matrix_jitsi_bot.interactions.base.BotInteraction.react_to_matrix_message`,
        prune the conversation, send any reply, and leave the room if
        it was flagged to.

        Deliberately doesn't use niobot's own ``client.is_old(event)`` -
        that drops anything sent before *this process* started, which
        would also discard a message that arrived while the bot was
        offline and is only now showing up in its first sync after
        restarting. Instead, ``event_id`` (globally unique - see
        :py:attr:`~matrix_jitsi_bot.db.models.conversation.Message.event_id`)
        is checked directly: an event already recorded is skipped (it
        was already handled, whether just now or in a previous run),
        anything else is processed, arrived late or not.

        Wraps the whole thing in a catch-all: an unhandled exception
        here would otherwise silently drop this one event (and any
        reply it should have gotten), while the bot's own event loop
        keeps running regardless - this way a bug in a single event,
        room, or reaction is visible in the logs (see ``-v``/``-vv``)
        instead of vanishing.
        """
        if event.sender == client.user_id:
            return

        try:
            from asgiref.sync import sync_to_async

            from matrix_jitsi_bot.db.models import Account, Message, Room

            already_handled = await sync_to_async(
                Message.objects.filter(event_id=event.event_id).exists
            )()
            if already_handled:
                return

            logger.debug(
                "Message from %s in %s: %r", event.sender, room.room_id, event.body
            )
            account = await sync_to_async(
                Account.objects.filter(user_id=client.user_id).first
            )()
            conversation, message = await sync_to_async(Room.record_message_of)(
                room.room_id, event, account=account
            )

            self.refresh_members = lambda: Room.sync_members_of(
                room.room_id,
                dict(room.users),
                dict(room.invited_users),
                room.power_levels.get_user_level,
                account=account,
            )
            try:
                result = await sync_to_async(self.react_to_matrix_message)(conversation)
            except Exception:
                result = None
                logger.exception(
                    "%s failed to handle a message from %s in %s",
                    type(self).__name__,
                    event.sender,
                    room.room_id,
                )
            finally:
                self.refresh_members = None

            important = result is not None or message.mentions_bot(client.user_id)
            await sync_to_async(conversation.prune)(message.id, important=important)

            if result is None:
                return
            logger.debug(
                "%s replied to %s in %s: %r",
                type(self).__name__,
                event.sender,
                room.room_id,
                result,
            )
            await result.send_message(client)

            from matrix_jitsi_bot.bot import MatrixJitsiBot

            await MatrixJitsiBot.leave_if_flagged(client, room.room_id)
        except Exception:
            logger.exception("Error handling a Matrix event")
