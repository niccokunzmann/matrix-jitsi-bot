from __future__ import annotations

from django.db import models

from .room import Room


class Conversation(models.Model):
    """The recorded message history of a room.

    Every incoming message is recorded as a
    :py:class:`~matrix_jitsi_bot.db.models.conversation.Message` here,
    so the bot's state can be replayed from the database instead of
    only from live Matrix traffic.
    """

    room = models.OneToOneField(
        Room, on_delete=models.CASCADE, related_name="conversation"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        """Which room this conversation belongs to."""
        return f"conversation in {self.room.room_id}"

    @property
    def last_message(self) -> Message | None:
        """The most recent
        :py:class:`~matrix_jitsi_bot.db.models.conversation.Message` in
        this conversation, or ``None`` if empty.
        """
        return self.messages.last()

    def prune(self, message_id: int, *, important: bool) -> None:
        """Keep this conversation's history bounded and relevant.

        Gap filled from the spec: only the message just handled
        (``message_id``) is checked for importance here (deleted
        immediately if not ``important``) - older messages already
        kept aren't retroactively re-evaluated, only trimmed down to
        ``settings.MAX_CONVERSATION_MESSAGES`` if there's more than
        that many.
        """
        from django.conf import settings

        if not important:
            self.messages.filter(id=message_id).delete()

        keep_ids = self.messages.order_by("-id")[: settings.MAX_CONVERSATION_MESSAGES]
        self.messages.exclude(
            id__in=list(keep_ids.values_list("id", flat=True))
        ).delete()


class Message(models.Model):
    """A single raw Matrix message recorded as part of a
    :py:class:`~matrix_jitsi_bot.db.models.conversation.Conversation`.
    """

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    sender = models.CharField(
        max_length=255, help_text="The Matrix user ID that sent the message."
    )
    event_id = models.CharField(
        max_length=255,
        unique=True,
        help_text="The Matrix event ID, unique homeserver-wide.",
    )
    body = models.TextField(help_text="The raw message text.")
    server_timestamp = models.DateTimeField(
        help_text="When the homeserver says this was sent."
    )
    source = models.JSONField(
        default=dict,
        blank=True,
        help_text="The raw Matrix event, for anything not in its own field.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        """Who sent this message, and its body."""
        return f"{self.sender}: {self.body!r}"

    @property
    def sanitized_body(self) -> str:
        """``body`` with whitespace normalised to single spaces.

        Collapses multi-line bodies, tabs, and repeated spaces so
        ``@conversation`` patterns don't each have to account for them.
        """
        return " ".join(self.body.strip().split())

    def mentions_bot(self, bot_user_id: str) -> bool:
        """Whether this message mentions the bot at all, anywhere in
        its body.

        Gap filled from the spec: a Matrix client typically renders a
        mention pill as the mentioned user's full ID in the plain-text
        fallback body, so a substring check is a simple, reasonably
        robust way to tell - regardless of a
        :py:class:`~matrix_jitsi_bot.interactions.base.MessageReaction`'s
        own, stricter "must be the very first word" rule (see
        :py:class:`~matrix_jitsi_bot.interactions.base.Mention`).
        """
        return bot_user_id in self.body


class CommandReply(models.Model):
    """A rich reply from a
    :py:class:`~matrix_jitsi_bot.interactions.base.BotInteraction`
    handler, tied to the message it answers.

    Unlike a plain string reply, a
    :py:class:`~matrix_jitsi_bot.db.models.conversation.CommandReply`
    is persisted.
    """

    message = models.ForeignKey(
        Message, on_delete=models.CASCADE, related_name="replies"
    )
    text = models.TextField(help_text="The plain-text reply.")
    html = models.TextField(
        blank=True, default="", help_text="Optional HTML-formatted reply."
    )
    reaction = models.CharField(
        max_length=8,
        blank=True,
        default="",
        help_text=(
            "An emoji to react to the triggering message with, e.g. "
            "✅/❌ for a Config command's success/failure - empty for none."
        ),
    )
    sent = models.BooleanField(
        default=False,
        help_text="Whether this reply was sent to Matrix successfully.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        """Which message this reply answers."""
        return f"reply to {self.message!r}"

    async def send_message(self, client) -> None:
        """Send this reply via ``client``, as a reply to the message it
        answers - and, if
        :py:attr:`~matrix_jitsi_bot.db.models.conversation.CommandReply.reaction`
        is set, react to that message with it too.

        ``self`` is saved with ``sent=False`` (see
        :py:class:`~matrix_jitsi_bot.interactions.base.BotInteraction`)
        before this ever runs; on success it's flipped to ``sent=True``,
        so a
        :py:class:`~matrix_jitsi_bot.db.models.conversation.CommandReply`
        still ``sent=False`` means sending it crashed or was never
        attempted.
        """
        from asgiref.sync import sync_to_async

        room_id = self.message.conversation.room.room_id
        await client.send_message(
            room_id,
            self.html or self.text,
            reply_to=self.message.event_id,
            content_type="html.raw" if self.html else "markdown",
        )
        if self.reaction:
            await client.add_reaction(room_id, self.message.event_id, self.reaction)
        self.sent = True
        await sync_to_async(self.save)(update_fields=["sent"])
