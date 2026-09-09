from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import models

from .account import Account

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    import nio

    from .conversation import Conversation, Message

#: Matrix rooms grade members by an integer power level. There's no single
#: spec-mandated meaning, but by the widely-used convention (Element's UI,
#: and the spec's own example power levels), 0 is a Default member, 50 is
#: a Moderator, and 100 is an Admin. Moderator-or-above is our bar for
#: letting someone configure the bot from within a room.
MODERATOR_POWER_LEVEL = 50


class Room(models.Model):
    """A Matrix room the bot has been invited into, with its own settings."""

    room_id = models.CharField(
        max_length=255,
        unique=True,
        help_text="The Matrix room ID, e.g. !abc123:matrix.org",
    )
    account = models.ForeignKey(
        Account,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="rooms",
        help_text=(
            "Which bot account is in this room - set when the bot joins "
            "it (or reconciles finding itself already joined) while "
            "running as that account. `null` for a room from before "
            "this field existed, until the bot next joins/reconciles it."
        ),
    )
    paused = models.BooleanField(
        default=False,
        help_text="While paused, the bot ignores everything except unpausing.",
    )
    should_leave = models.BooleanField(
        default=False,
        help_text=(
            "Set by the `leave` command; `bot.py` acts on it (calling "
            "the Matrix API to actually leave) once the reply announcing "
            "it has been sent, then deletes this row."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        """This room's Matrix room ID."""
        return self.room_id

    def is_moderator(self, matrix_handle: str) -> bool:
        """Whether ``matrix_handle`` is at least a Moderator in this room.

        That means a Matrix power level of
        :py:data:`~matrix_jitsi_bot.db.models.room.MODERATOR_POWER_LEVEL`
        (50) or higher - see the module-level constant for what that
        means. A user we have no membership record for is never a
        moderator.
        """
        member = self.members.filter(user_id=matrix_handle).first()
        return member is not None and member.power_level >= MODERATOR_POWER_LEVEL

    def moderators(self) -> list[str]:
        """User IDs of every Moderator-or-above member - see
        :py:meth:`~matrix_jitsi_bot.db.models.room.Room.is_moderator`.
        """
        return list(
            self.members.filter(power_level__gte=MODERATOR_POWER_LEVEL).values_list(
                "user_id", flat=True
            )
        )

    def ensure_account(self, account: Account | None) -> None:
        """Tag this room with ``account``, if it isn't already tagged
        with one - a no-op if ``account`` is ``None`` or this room
        already has one (never overwrites an existing tag).

        Called wherever a room gets touched while the bot is actually
        running as some account (joining, syncing members, recording a
        message), so a room from before
        :py:attr:`~matrix_jitsi_bot.db.models.room.Room.account`
        existed - or one
        :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.reconcile_joined_rooms`
        recreated bare - picks it up the next time it's active, without
        ever needing a one-off migration.
        """
        if account is not None and self.account_id is None:
            self.account = account
            self.save(update_fields=["account"])

    def sync_members(
        self,
        users: Iterable[str],
        invited_users: Iterable[str],
        get_power_level: Callable[[str], int],
    ) -> None:
        """Replace this room's
        :py:class:`~matrix_jitsi_bot.db.models.room.RoomMember` rows
        with the given joined/invited users, marking anyone no longer
        in either as having left.
        """
        seen: set[str] = set()
        for user_id in users:
            RoomMember.objects.update_or_create(
                room=self,
                user_id=user_id,
                defaults={
                    "membership": "join",
                    "power_level": get_power_level(user_id),
                },
            )
            seen.add(user_id)
        for user_id in invited_users:
            RoomMember.objects.update_or_create(
                room=self,
                user_id=user_id,
                defaults={
                    "membership": "invite",
                    "power_level": get_power_level(user_id),
                },
            )
            seen.add(user_id)
        self.members.exclude(user_id__in=seen).update(membership="leave")

    @classmethod
    def sync_members_of(
        cls,
        room_id: str,
        users: Iterable[str],
        invited_users: Iterable[str],
        get_power_level: Callable[[str], int],
        *,
        account: Account | None = None,
    ) -> None:
        """Resolve ``room_id`` to a
        :py:class:`~matrix_jitsi_bot.db.models.room.Room` - creating it
        if this is the first anything's heard about it - and
        :py:meth:`~matrix_jitsi_bot.db.models.room.Room.sync_members`
        on it.

        ``account`` tags which bot account this room belongs to, if
        it isn't already tagged - see
        :py:attr:`~matrix_jitsi_bot.db.models.room.Room.account`.
        """
        room, _ = cls.objects.get_or_create(room_id=room_id)
        room.ensure_account(account)
        room.sync_members(users, invited_users, get_power_level)

    def record_message(
        self, event: nio.RoomMessageText
    ) -> tuple[Conversation, Message]:
        """Record an incoming Matrix ``event`` as a
        :py:class:`~matrix_jitsi_bot.db.models.conversation.Message` in
        this room, creating its
        :py:class:`~matrix_jitsi_bot.db.models.conversation.Conversation`
        if needed. Returns the conversation and the new message.
        """
        from datetime import UTC, datetime

        from .conversation import Conversation, Message

        conversation, _ = Conversation.objects.get_or_create(room=self)
        message = Message.objects.create(
            conversation=conversation,
            sender=event.sender,
            event_id=event.event_id,
            body=event.body,
            server_timestamp=datetime.fromtimestamp(
                event.server_timestamp / 1000, tz=UTC
            ),
            source=event.source,
        )
        return conversation, message

    @classmethod
    def record_message_of(
        cls, room_id: str, event: nio.RoomMessageText, *, account: Account | None = None
    ) -> tuple[Conversation, Message]:
        """Resolve ``room_id`` to a
        :py:class:`~matrix_jitsi_bot.db.models.room.Room` - creating it
        if needed - and
        :py:meth:`~matrix_jitsi_bot.db.models.room.Room.record_message`
        on it.

        ``account`` tags which bot account this room belongs to, if
        it isn't already tagged - see
        :py:meth:`~matrix_jitsi_bot.db.models.room.Room.ensure_account`.
        """
        room, _ = cls.objects.get_or_create(room_id=room_id)
        room.ensure_account(account)
        return room.record_message(event)

    @classmethod
    def is_flagged_to_leave(cls, room_id: str) -> bool:
        """Whether the room ``room_id`` is flagged to be left (see
        :py:attr:`~matrix_jitsi_bot.db.models.room.Room.should_leave`).
        """
        return cls.objects.filter(room_id=room_id, should_leave=True).exists()

    @classmethod
    def forget(cls, room_id: str) -> None:
        """Delete the ``room_id`` row (cascading to everything recorded
        about it).
        """
        cls.objects.filter(room_id=room_id).delete()

    @classmethod
    def forget_others(cls, account: Account, keep_room_ids: Iterable[str]) -> list[str]:
        """Delete every room tagged to ``account`` whose ``room_id``
        isn't in ``keep_room_ids``, returning the deleted IDs (for the
        caller to log).

        Used by
        :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.reconcile_joined_rooms`
        to forget a room the bot was removed from (kicked, banned, or
        otherwise) while it wasn't running to see the membership event
        that caused it - ``keep_room_ids`` there is ``client.rooms``,
        so anything tagged to this account but missing from it is no
        longer actually joined.
        """
        stale = list(
            cls.objects.filter(account=account)
            .exclude(room_id__in=list(keep_room_ids))
            .values_list("room_id", flat=True)
        )
        cls.objects.filter(room_id__in=stale).delete()
        return stale


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
        """This member's user ID, membership state, power level, and room."""
        status = f"{self.membership}, power={self.power_level}"
        return f"{self.user_id} ({status}) in {self.room.room_id}"
