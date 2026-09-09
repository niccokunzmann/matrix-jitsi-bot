from __future__ import annotations

from django.db import models

# Matrix rooms grade members by an integer power level. There's no single
# spec-mandated meaning, but by the widely-used convention (Element's UI,
# and the spec's own example power levels), 0 is a Default member, 50 is
# a Moderator, and 100 is an Admin. Moderator-or-above is our bar for
# letting someone configure the bot from within a room.
MODERATOR_POWER_LEVEL = 50


class Account(models.Model):
    """A Matrix account the bot can log in and run as.

    Holds everything nio-bot needs to log in: either a password, or a
    device ID and access token from a previous login.
    """

    homeserver = models.URLField(
        help_text="The Matrix homeserver URL, e.g. https://matrix.org"
    )
    user_id = models.CharField(
        max_length=255,
        unique=True,
        help_text="The bot's Matrix user ID, e.g. @bot:matrix.org",
    )
    device_id = models.CharField(max_length=255, blank=True, default="")
    access_token = models.CharField(max_length=1024, blank=True, default="")
    password = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.user_id


class Room(models.Model):
    """A Matrix room the bot has been invited into, with its own settings."""

    room_id = models.CharField(
        max_length=255,
        unique=True,
        help_text="The Matrix room ID, e.g. !abc123:matrix.org",
    )
    language = models.CharField(
        max_length=8,
        default="en",
        help_text="The language the bot speaks in this room.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.room_id

    def is_moderator(self, matrix_handle: str) -> bool:
        """Whether `matrix_handle` is at least a Moderator in this room.

        That means a Matrix power level of `MODERATOR_POWER_LEVEL` (50) or
        higher - see the module-level constant for what that means. A user
        we have no membership record for is never a moderator.
        """
        member = self.members.filter(user_id=matrix_handle).first()
        return member is not None and member.power_level >= MODERATOR_POWER_LEVEL


class RoomMember(models.Model):
    """A Matrix user's membership in a room, as last observed from a sync."""

    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="members")
    user_id = models.CharField(
        max_length=255, help_text="The Matrix user ID of the member."
    )
    membership = models.CharField(
        max_length=16,
        default="join",
        help_text="The member's membership state: join, invite, leave, ban, or knock.",
    )
    power_level = models.IntegerField(
        default=0, help_text="The member's Matrix power level in this room."
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["room", "user_id"], name="unique_room_member"
            ),
        ]

    def __str__(self) -> str:
        status = f"{self.membership}, power={self.power_level}"
        return f"{self.user_id} ({status}) in {self.room.room_id}"


class Conversation(models.Model):
    """The recorded message history of a room.

    Every incoming message is recorded as a `Message` here, so the bot's
    state can be replayed from the database instead of only from live
    Matrix traffic.
    """

    room = models.OneToOneField(
        Room, on_delete=models.CASCADE, related_name="conversation"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"conversation in {self.room.room_id}"

    @property
    def last_message(self) -> Message | None:
        """The most recent `Message` in this conversation, or `None` if empty."""
        return self.messages.last()


class Message(models.Model):
    """A single raw Matrix message recorded as part of a `Conversation`."""

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
        return f"{self.sender}: {self.body!r}"

    @property
    def sanitized_body(self) -> str:
        """`body` with whitespace normalised to single spaces.

        Collapses multi-line bodies, tabs, and repeated spaces so
        `@conversation` patterns don't each have to account for them.
        """
        return " ".join(self.body.split())


class CommandReply(models.Model):
    """A rich reply from a `BotInteraction` handler, tied to the message it answers.

    Unlike a plain string reply, a CommandReply is persisted.
    """

    message = models.ForeignKey(
        Message, on_delete=models.CASCADE, related_name="replies"
    )
    text = models.TextField(help_text="The plain-text reply.")
    html = models.TextField(
        blank=True, default="", help_text="Optional HTML-formatted reply."
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"reply to {self.message!r}"

    async def send_message(self, client) -> None:
        """Send this reply via `client`, as a reply to the message it answers."""
        await client.send_message(
            self.message.conversation.room.room_id,
            self.html or self.text,
            reply_to=self.message.event_id,
            content_type="html.raw" if self.html else "markdown",
        )
