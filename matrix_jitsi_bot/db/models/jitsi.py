"""Jitsi conference tracking: its models.

See :py:mod:`matrix_jitsi_bot.interactions.jitsi` for the chat commands
that work with them.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from django.db import models
from django.db.models import Q
from django.utils import timezone

from .account import Account
from .process import JitsiMonitor
from .room import Room

if TYPE_CHECKING:
    from matrix_jitsi_bot.jitsi import JitsiChange, JitsiStatus

#: How long since a conference was last seen open before its next check
#: backs off to each tier - checked most often right after being open,
#: most rarely once it's been quiet for a month. Order matters: the
#: first matching (i.e. longest) threshold wins.
_CHECK_INTERVAL_TIERS = (
    (timedelta(days=30), 60),
    (timedelta(days=7), 15),
    (timedelta(days=1), 5),
    (timedelta(0), 1),
)

#: Every :py:class:`~matrix_jitsi_bot.db.models.jitsi.TrackedJitsiRoom`
#: boolean field a tracker can set, in the order they're checked/shown.
_TRACK_FIELDS = (
    "track_open",
    "track_close",
    "track_starts",
    "track_joins",
    "track_leaves",
    "show_speaker",
)


class JitsiRoom(models.Model):
    """A Jitsi conference, identified by its URL.

    Its status is shared across every matrix
    :py:class:`~matrix_jitsi_bot.db.models.room.Room` that tracks it via
    a :py:class:`~matrix_jitsi_bot.db.models.jitsi.TrackedJitsiRoom` -
    checking it once serves every room tracking it.
    """

    url = models.URLField(unique=True, help_text="The Jitsi conference URL.")
    is_open = models.BooleanField(default=False)
    participants = models.JSONField(
        default=list, blank=True, help_text="Names last seen in the conference."
    )
    last_checked_at = models.DateTimeField(
        null=True, blank=True, help_text="When this was last checked at all."
    )
    last_opened_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this was last seen open - picks the next check interval.",
    )
    next_check_at = models.DateTimeField(default=timezone.now)

    def __str__(self) -> str:
        """This conference's URL."""
        return self.url

    def hostname(self) -> str:
        """This conference's URL's hostname, e.g. ``"meet.example.org"``."""
        return urlparse(self.url).hostname or ""

    def short_name(self) -> str:
        """This conference's URL's last path segment, e.g.
        ``"matrix-jitsi-bot"`` for
        ``https://meet.hosted.quelltext.eu/matrix-jitsi-bot`` - the
        closest thing to a "room name" a Jitsi URL carries.
        """
        return urlparse(self.url).path.rstrip("/").rsplit("/", 1)[-1]

    def next_check_interval(self) -> int:
        """Seconds until this conference should be checked again, based on
        how long it's been since it was last seen open (never, if it
        never has).
        """
        if self.last_opened_at is None:
            return _CHECK_INTERVAL_TIERS[-1][1]
        since = timezone.now() - self.last_opened_at
        for threshold, seconds in _CHECK_INTERVAL_TIERS:
            if since >= threshold:
                return seconds
        return _CHECK_INTERVAL_TIERS[-1][1]

    def wants_participants_check(self) -> bool:
        """Whether the next check should fetch participants at all.

        While closed, only if some unpaused tracker wants
        ``track_starts``, ``track_joins`` or ``track_leaves`` - the
        first check that finds it open needs a baseline participant
        list either way, to report "who started it" and/or to diff
        later joins/leaves against.

        While open, only if some unpaused tracker wants ``track_joins``
        or ``track_leaves`` - continuous monitoring. A tracker that
        only wants ``track_starts`` already got its one snapshot on the
        check that found it open, and doesn't need another until it
        closes and reopens.
        """
        trackers = self.tracked_by.filter(room__paused=False)
        if self.is_open:
            return trackers.filter(Q(track_joins=True) | Q(track_leaves=True)).exists()
        return trackers.filter(
            Q(track_starts=True) | Q(track_joins=True) | Q(track_leaves=True)
        ).exists()

    def describe(self) -> str:
        """A one-line human-readable summary of this room's last-known status."""
        if not self.is_open:
            return f"{self.url}: closed"
        if not self.participants:
            return f"{self.url}: open, empty"
        names = ", ".join(self.participants)
        return f"{self.url}: open, with {names}"

    def apply_status(self, status: JitsiStatus) -> JitsiChange:
        """Update this conference with a freshly-observed ``status``,
        saving it.

        Returns what changed - see
        :py:class:`~matrix_jitsi_bot.jitsi.JitsiChange`. A
        ``status.participants`` of ``None`` (not checked) leaves
        ``self.participants`` as it was, and is never reported as a
        starters/joined/left change.
        """
        from matrix_jitsi_bot.jitsi import JitsiChange

        now = timezone.now()
        was_open = self.is_open
        old_participants = self.participants

        self.last_checked_at = now
        opened = status.is_open and not was_open
        closed = was_open and not status.is_open

        starters: list[str] | None = None
        joined: list[str] = []
        left: list[str] = []

        if status.is_open:
            self.last_opened_at = now
            if status.participants is not None:
                if opened:
                    starters = list(status.participants)
                else:
                    new_participants = set(status.participants)
                    old_set = set(old_participants)
                    joined = [p for p in status.participants if p not in old_set]
                    left = [p for p in old_participants if p not in new_participants]
                self.participants = status.participants
        else:
            self.participants = []

        self.is_open = status.is_open
        self.next_check_at = now + timedelta(seconds=self.next_check_interval())
        self.save()

        return JitsiChange(
            opened=opened, closed=closed, starters=starters, joined=joined, left=left
        )

    @classmethod
    def due(cls) -> list[JitsiRoom]:
        """Every conference whose next check is now due."""
        return list(cls.objects.filter(next_check_at__lte=timezone.now()))

    @classmethod
    def tracked(cls) -> list[JitsiRoom]:
        """Every conference tracked by at least one
        :py:class:`~matrix_jitsi_bot.db.models.jitsi.TrackedJitsiRoom`,
        regardless of whether it's currently due - see
        :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.poll_jitsi_rooms_all`.
        """
        return list(cls.objects.filter(tracked_by__isnull=False).distinct())

    @classmethod
    def is_anything_tracked(cls) -> bool:
        """Whether at least one conference is tracked anywhere - see
        :py:meth:`~matrix_jitsi_bot.db.models.jitsi.JitsiRoom.tracked`.
        Cheaper than that when only the yes/no answer is needed, e.g.
        :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.poll_jitsi_rooms_forever`
        deciding how long to sleep.
        """
        return cls.objects.filter(tracked_by__isnull=False).exists()

    def trackers_of(self, change: JitsiChange) -> list[TrackedJitsiRoom]:
        """Every unpaused
        :py:class:`~matrix_jitsi_bot.db.models.jitsi.TrackedJitsiRoom`
        of this conference that has at least one message to hear about
        ``change`` - see
        :py:meth:`~matrix_jitsi_bot.jitsi.JitsiChange.messages_for`.
        """
        candidates = TrackedJitsiRoom.objects.filter(
            jitsi_room=self, room__paused=False
        ).select_related("room")
        return [tracked for tracked in candidates if change.messages_for(self, tracked)]

    async def notify_trackers(self, client, change: JitsiChange) -> None:
        """Tell every :py:class:`~matrix_jitsi_bot.db.models.room.Room`
        tracking this conference whatever it asked to hear about
        ``change``.
        """
        from asgiref.sync import sync_to_async

        trackers = await sync_to_async(self.trackers_of)(change)
        for tracked in trackers:
            text = "\n".join(change.messages_for(self, tracked))
            await client.send_message(tracked.room.room_id, text)

    def wants_monitoring(self) -> bool:
        """Whether this conference should be monitored by staying in it
        (see :py:func:`~matrix_jitsi_bot.jitsi.monitor_jitsi_room`)
        instead of being checked at intervals: while it is open, and
        some unpaused tracker wants ``track_joins`` or ``track_leaves``.
        Only they need to see changes as they happen - see
        :py:meth:`~matrix_jitsi_bot.db.models.jitsi.JitsiRoom.wants_participants_check`.
        """
        return self.is_open and self.wants_participants_check()

    async def monitor_and_notify(self, client, process=None) -> None:
        """Stay in this conference, apply every status change to it and
        notify its trackers (see
        :py:meth:`~matrix_jitsi_bot.db.models.jitsi.JitsiRoom.notify_trackers`),
        until it is closed - or this is cancelled, which leaves it.
        While in it, a :py:class:`~matrix_jitsi_bot.db.models.process.JitsiMonitor`
        exists for it, owned by ``process``.

        Discloses ``client``'s own account's display name, like
        :py:meth:`~matrix_jitsi_bot.db.models.jitsi.JitsiRoom.check_and_notify`.
        """
        from asgiref.sync import sync_to_async

        from matrix_jitsi_bot.jitsi import monitor_jitsi_room

        display_name = await sync_to_async(Account.display_name_of)(client.user_id)
        monitor = await sync_to_async(JitsiMonitor.begin)(self, process)
        try:
            async for status in monitor_jitsi_room(self.url, name=display_name):
                await sync_to_async(monitor.record)(status)
                change = await sync_to_async(self.apply_status)(status)
                if change:
                    await self.notify_trackers(client, change)
        finally:
            await sync_to_async(JitsiMonitor.end)(self)

    async def check_and_notify(self, client) -> None:
        """Check this conference, apply the result, and notify its
        trackers (see
        :py:meth:`~matrix_jitsi_bot.db.models.jitsi.JitsiRoom.notify_trackers`)
        if anything changed.

        Discloses ``client``'s own account's
        :py:meth:`~matrix_jitsi_bot.db.models.account.Account.display_name_of`
        while checking, read fresh from the database every time - see
        :py:func:`~matrix_jitsi_bot.jitsi.check_jitsi_room`.
        """
        from asgiref.sync import sync_to_async

        from matrix_jitsi_bot.jitsi import check_jitsi_room

        want_participants = await sync_to_async(self.wants_participants_check)()
        display_name = await sync_to_async(Account.display_name_of)(client.user_id)
        status = await check_jitsi_room(
            self.url, want_participants=want_participants, name=display_name
        )
        change = await sync_to_async(self.apply_status)(status)
        if change:
            await self.notify_trackers(client, change)


class TrackedJitsiRoom(models.Model):
    """One matrix :py:class:`~matrix_jitsi_bot.db.models.room.Room`'s
    tracking configuration for one
    :py:class:`~matrix_jitsi_bot.db.models.jitsi.JitsiRoom`.

    Each ``track_*`` field is independently toggled by a chat command
    (see :py:data:`~matrix_jitsi_bot.interactions.chat_notification._FLAG_FIELDS`); a
    row with every field ``False`` isn't tracking anything and is
    deleted rather than kept around - see
    :py:func:`~matrix_jitsi_bot.interactions.jitsi._untrack`.
    """

    room = models.ForeignKey(
        Room, on_delete=models.CASCADE, related_name="tracked_jitsi_rooms"
    )
    jitsi_room = models.ForeignKey(
        JitsiRoom, on_delete=models.CASCADE, related_name="tracked_by"
    )
    track_open = models.BooleanField(
        default=False, help_text="Report when the conference opens."
    )
    track_close = models.BooleanField(
        default=False, help_text="Report when the conference closes."
    )
    track_starts = models.BooleanField(
        default=False,
        help_text="Report who's in the conference the moment it's noticed open.",
    )
    track_joins = models.BooleanField(
        default=False, help_text="Report individual joins while it's open."
    )
    track_leaves = models.BooleanField(
        default=False, help_text="Report individual leaves while it's open."
    )
    show_speaker = models.BooleanField(
        default=False,
        help_text="Show a speaker on the room's avatar while it's open.",
    )
    avatar_spaces = models.ManyToManyField(
        "matrix_jitsi_bot.Space",
        blank=True,
        related_name="tracked_by",
        help_text="Spaces whose avatar shows a speaker while it's open.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["room", "jitsi_room"], name="unique_tracked_jitsi_room"
            ),
        ]

    def __str__(self) -> str:
        """Which conference, tracked in which room."""
        return f"{self.jitsi_room.url} tracked in {self.room.room_id}"

    def is_tracking_anything(self) -> bool:
        """Whether any ``track_*`` field is set, or a space's avatar is
        changed - see the class docstring.
        """
        return any(getattr(self, field) for field in _TRACK_FIELDS) or (
            self.pk is not None and self.avatar_spaces.exists()
        )

    def set_track_field(self, field: str, *, value: bool) -> None:
        """Set one ``track_*`` field to ``value``, without saving.

        Raises :py:exc:`ValueError` if ``field`` isn't one of
        :py:data:`~matrix_jitsi_bot.db.models.jitsi._TRACK_FIELDS` -
        guards against a typo in
        :py:data:`~matrix_jitsi_bot.interactions.chat_notification._FLAG_FIELDS`
        silently setting an unrelated attribute instead of a tracking
        flag.
        """
        if field not in _TRACK_FIELDS:
            raise ValueError(f"{field!r} is not a tracking field: {_TRACK_FIELDS}")
        setattr(self, field, value)
