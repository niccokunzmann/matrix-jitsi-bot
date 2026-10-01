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


def _escape_control_characters(text: str) -> str:
    """``text`` with every non-printable character - newlines included -
    replaced by a backslash escape, so it's always safe to print on a
    single line.

    A Matrix room name is attacker-controlled (any member with
    sufficient power level can set it) and isn't restricted to
    printable text, so this guards
    :py:meth:`~matrix_jitsi_bot.db.models.room.Room.label` (and
    anything printing it, like ``matrix-jitsi-bot status``) against a
    name containing a newline, carriage return, ANSI escape sequence,
    or similar - which could otherwise inject fake extra lines/rooms
    into that output.
    """
    escapes = {"\n": "\\n", "\r": "\\r", "\t": "\\t", "\\": "\\\\"}
    result = []
    for char in text:
        if char in escapes:
            result.append(escapes[char])
        elif char.isprintable():
            result.append(char)
        elif ord(char) < 0x100:
            result.append(f"\\x{ord(char):02x}")
        else:
            result.append(f"\\u{ord(char):04x}")
    return "".join(result)


class Room(models.Model):
    """A Matrix room the bot has been invited into, with its own settings."""

    room_id = models.CharField(
        max_length=255,
        unique=True,
        help_text="The Matrix room ID, e.g. !abc123:matrix.org",
    )
    name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text=(
            "This room's Matrix display name, as last observed - empty "
            "if never observed (e.g. a room from before this field "
            "existed, until the bot next sees it)."
        ),
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
    speaker_shown = models.BooleanField(
        default=False,
        help_text=(
            "Whether the room's avatar currently has the speaker "
            "overlay. While set, `original_avatar` holds what to restore."
        ),
    )
    original_avatar = models.BinaryField(
        null=True,
        blank=True,
        help_text=(
            "The avatar image the room had before the speaker overlay, "
            "cached only while `speaker_shown`. Empty: it had none."
        ),
    )
    original_avatar_type = models.CharField(
        max_length=255, blank=True, default="", help_text="Its content type."
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

    def wants_speaker(self) -> bool:
        """Whether the room's avatar should show the speaker now: it is
        not paused, and it tracks a conference with ``show_speaker``
        that is open.
        """
        return (
            not self.paused
            and self.tracked_jitsi_rooms.filter(
                show_speaker=True, jitsi_room__is_open=True
            ).exists()
        )

    def cache_avatar(self, image: bytes | None, content_type: str = "") -> None:
        """Remember the room's ``image`` (``None``: it has none) as the
        one to restore, and that the speaker is shown.
        """
        self.original_avatar = image
        self.original_avatar_type = content_type
        self.speaker_shown = True
        self.save(
            update_fields=["original_avatar", "original_avatar_type", "speaker_shown"]
        )

    def uncache_avatar(self) -> None:
        """Remove the cached avatar from the database - it is restored."""
        self.original_avatar = None
        self.original_avatar_type = ""
        self.speaker_shown = False
        self.save(
            update_fields=["original_avatar", "original_avatar_type", "speaker_shown"]
        )

    @classmethod
    def with_speaker_work(cls, account: Account) -> list[Room]:
        """The rooms of ``account`` that show a speaker or track a
        conference to show it for.
        """
        from django.db.models import Q

        return list(
            cls.objects.filter(account=account)
            .filter(Q(speaker_shown=True) | Q(tracked_jitsi_rooms__show_speaker=True))
            .distinct()
        )

    def moderators(self) -> list[str]:
        """User IDs of every Moderator-or-above member - see
        :py:meth:`~matrix_jitsi_bot.db.models.room.Room.is_moderator`.
        """
        return list(
            self.members.filter(power_level__gte=MODERATOR_POWER_LEVEL).values_list(
                "user_id", flat=True
            )
        )

    def label(self) -> str:
        """This room as a human-readable, single-line label: its
        Matrix room ID alone if it has no stored
        :py:attr:`~matrix_jitsi_bot.db.models.room.Room.name`, or
        ``"name"(room_id)`` with the name's control characters
        (including newlines) escaped - see
        :py:func:`~matrix_jitsi_bot.db.models.room._escape_control_characters` -
        so a room named to look like extra output can't break
        ``matrix-jitsi-bot status`` or similar single-line reporting.
        """
        if not self.name:
            return self.room_id
        return f'"{_escape_control_characters(self.name)}"({self.room_id})'

    def update_name(self, name: str | None) -> None:
        """Update this room's stored
        :py:attr:`~matrix_jitsi_bot.db.models.room.Room.name` to
        ``name``, saving only if it actually changed.

        ``name`` is ``None`` for a Matrix room nio hasn't computed a
        name for yet - treated the same as ``""``, rather than
        overwriting a previously-observed name with nothing.
        """
        name = name or ""
        if name != self.name:
            self.name = name
            self.save(update_fields=["name"])

    @classmethod
    def update_name_of(cls, room_id: str, name: str | None) -> None:
        """Resolve ``room_id`` to a
        :py:class:`~matrix_jitsi_bot.db.models.room.Room` - creating it
        if needed - and
        :py:meth:`~matrix_jitsi_bot.db.models.room.Room.update_name`
        on it.
        """
        room, _ = cls.objects.get_or_create(room_id=room_id)
        room.update_name(name)

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
