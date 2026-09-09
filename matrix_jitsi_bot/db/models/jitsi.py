"""Jitsi conference tracking: its models, and the chat commands for it.

See :doc:`/using-a-bot/index` for the commands
:py:class:`~matrix_jitsi_bot.db.models.jitsi.JitsiInteraction`
implements.
"""

from __future__ import annotations

from collections import Counter
from datetime import timedelta
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from django.db import models
from django.db.models import Q
from django.utils import timezone

from matrix_jitsi_bot.interactions.base import (
    BotInteraction,
    CommandError,
    Config,
    Mention,
)
from matrix_jitsi_bot.jitsi import NO_BOT_MARKER, opts_out_of_bot

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
)

#: The chat phrase following "track"/"don't track", to the
#: :py:data:`~matrix_jitsi_bot.db.models.jitsi._TRACK_FIELDS` it sets -
#: see :py:func:`~matrix_jitsi_bot.db.models.jitsi._track` and
#: :py:func:`~matrix_jitsi_bot.db.models.jitsi._untrack`.
_FLAG_FIELDS = {
    "status of": ("track_open", "track_close"),
    "open status of": ("track_open",),
    "close status of": ("track_close",),
    "who is in": ("track_joins", "track_leaves"),
    "who joins": ("track_joins",),
    "who leaves": ("track_leaves",),
    "who starts": ("track_starts",),
}

_TRACK = 200
_UNTRACK_FLAG = 201
#: Tried before `_UNTRACK_ONE`'s bare-room pattern, which would
#: otherwise also match "don't track any" (with "any" parsed as a room
#: reference) - see `JitsiInteraction.react_to_untrack_any`.
_UNTRACK_ANY = 202
_UNTRACK_ONE = 203
_CHECK = 204
_STATUS = 205

_URL = r"https?://\S+"
#: A room reference: a full URL, a hostname, or a short name - see
#: :py:func:`~matrix_jitsi_bot.db.models.jitsi._resolve_tracked_room` -
#: or omitted entirely, in a named ``room`` group so it's ``None``
#: rather than missing from ``match.groupdict()``.
_ROOM = r"(?:\s+(?P<room>\S+))?"
_FLAG = (
    r"(?P<flag>status of|open status of|close status of"
    r"|who is in|who joins|who leaves|who starts)"
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

    async def check_and_notify(self, client) -> None:
        """Check this conference, apply the result, and notify its
        trackers (see
        :py:meth:`~matrix_jitsi_bot.db.models.jitsi.JitsiRoom.notify_trackers`)
        if anything changed.
        """
        from asgiref.sync import sync_to_async

        from matrix_jitsi_bot.jitsi import check_jitsi_room

        want_participants = await sync_to_async(self.wants_participants_check)()
        status = await check_jitsi_room(self.url, want_participants=want_participants)
        change = await sync_to_async(self.apply_status)(status)
        if change:
            await self.notify_trackers(client, change)


class TrackedJitsiRoom(models.Model):
    """One matrix :py:class:`~matrix_jitsi_bot.db.models.room.Room`'s
    tracking configuration for one
    :py:class:`~matrix_jitsi_bot.db.models.jitsi.JitsiRoom`.

    Each ``track_*`` field is independently toggled by a chat command
    (see :py:data:`~matrix_jitsi_bot.db.models.jitsi._FLAG_FIELDS`); a
    row with every field ``False`` isn't tracking anything and is
    deleted rather than kept around - see
    :py:func:`~matrix_jitsi_bot.db.models.jitsi._untrack`.
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
        """Whether any ``track_*`` field is set - see the class docstring."""
        return any(getattr(self, field) for field in _TRACK_FIELDS)

    def set_track_field(self, field: str, *, value: bool) -> None:
        """Set one ``track_*`` field to ``value``, without saving.

        Raises :py:exc:`ValueError` if ``field`` isn't one of
        :py:data:`~matrix_jitsi_bot.db.models.jitsi._TRACK_FIELDS` -
        guards against a typo in
        :py:data:`~matrix_jitsi_bot.db.models.jitsi._FLAG_FIELDS`
        silently setting an unrelated attribute instead of a tracking
        flag.
        """
        if field not in _TRACK_FIELDS:
            raise ValueError(f"{field!r} is not a tracking field: {_TRACK_FIELDS}")
        setattr(self, field, value)


class RoomReferenceNotFound(CommandError):
    """Raised by
    :py:func:`~matrix_jitsi_bot.db.models.jitsi._resolve_tracked_room`
    when a room reference doesn't identify exactly one tracked
    conference - its message is the chat reply to send.

    A :py:exc:`~matrix_jitsi_bot.interactions.base.CommandError`, so
    letting it propagate out of a
    :py:class:`~matrix_jitsi_bot.db.models.jitsi.JitsiInteraction`
    handler both replies with its message and reacts with ❌ - see
    that exception.
    """


def _describe_references(tracked: list[TrackedJitsiRoom]) -> str:
    """A bullet list of ``tracked`` conferences, each with its URL and -
    only where unique among ``tracked`` - its hostname and short name
    as usable shortcuts (see
    :py:func:`~matrix_jitsi_bot.db.models.jitsi._resolve_tracked_room`).
    An ambiguous hostname/short name (shared by more than one) is
    simply not offered, rather than offered as a shortcut that
    wouldn't resolve.
    """
    hostnames = Counter(t.jitsi_room.hostname() for t in tracked)
    short_names = Counter(t.jitsi_room.short_name() for t in tracked)
    lines = []
    for t in tracked:
        jitsi_room = t.jitsi_room
        host, short = jitsi_room.hostname(), jitsi_room.short_name()
        shortcuts = []
        if host and hostnames[host] == 1:
            shortcuts.append(host)
        if short and short != host and short_names[short] == 1:
            shortcuts.append(short)
        suffix = f" ({', '.join(shortcuts)})" if shortcuts else ""
        lines.append(f"- {jitsi_room.url}{suffix}")
    return "\n".join(lines)


def _resolve_tracked_room(room: Room, ref: str | None) -> JitsiRoom:
    """Resolve ``ref`` to one of ``room``'s tracked conferences.

    ``ref`` is a full URL, a hostname or short name - each only
    resolves if it's unique among what's tracked here, per
    :py:func:`~matrix_jitsi_bot.db.models.jitsi._describe_references`
    - or ``None``, which resolves only if exactly one conference is
    tracked here at all.

    Raises
    :py:exc:`~matrix_jitsi_bot.db.models.jitsi.RoomReferenceNotFound`
    (its message is the reply to send, listing what's available) if
    ``ref`` doesn't identify exactly one.
    """
    tracked = list(
        TrackedJitsiRoom.objects.filter(room=room).select_related("jitsi_room")
    )
    if not tracked:
        raise RoomReferenceNotFound("Nothing is being tracked in this room.")

    if ref is None:
        if len(tracked) == 1:
            return tracked[0].jitsi_room
        raise RoomReferenceNotFound(
            "Several conferences are tracked here - say which one:\n"
            + _describe_references(tracked)
        )

    if ref.startswith(("http://", "https://")):
        for entry in tracked:
            if entry.jitsi_room.url == ref:
                return entry.jitsi_room
        raise RoomReferenceNotFound(
            f"Not tracking {ref} in this room. Currently tracked:\n"
            + _describe_references(tracked)
        )

    matches = [
        entry.jitsi_room
        for entry in tracked
        if ref in (entry.jitsi_room.hostname(), entry.jitsi_room.short_name())
    ]
    if len(matches) == 1:
        return matches[0]
    raise RoomReferenceNotFound(
        f'"{ref}" doesn\'t uniquely identify a tracked conference here. '
        "Currently tracked:\n" + _describe_references(tracked)
    )


def _verify_new_jitsi_room(url: str) -> None:
    """Confirm ``url`` actually looks like a reachable Jitsi conference
    before it's tracked for the first time - only ever called for a
    ``url`` nothing tracks yet, see
    :py:func:`~matrix_jitsi_bot.db.models.jitsi._track`.

    Raises :py:exc:`~matrix_jitsi_bot.interactions.base.CommandError`
    (a friendly message, not the underlying exception) if
    :py:func:`~matrix_jitsi_bot.jitsi.check_jitsi_room` fails in any
    way - a typo, a non-Jitsi URL, or an unreachable host all look the
    same from here: not something worth tracking. Only whether the
    check itself succeeds matters, not what it finds - a closed but
    genuinely reachable conference is still fine to track.
    """
    import asyncio

    from matrix_jitsi_bot.jitsi import check_jitsi_room

    try:
        asyncio.run(check_jitsi_room(url, want_participants=False))
    except Exception as exc:
        raise CommandError(
            f"{url} doesn't look like a valid, reachable Jitsi room - not tracking it."
        ) from exc


def _track(conversation, ref: str | None, fields: tuple[str, ...]) -> str:
    """Set every field in ``fields`` on ``ref``'s tracking row in
    ``conversation``'s room, creating both the
    :py:class:`~matrix_jitsi_bot.db.models.jitsi.JitsiRoom` (only if
    ``ref`` is a full URL not tracked anywhere yet) and the
    :py:class:`~matrix_jitsi_bot.db.models.jitsi.TrackedJitsiRoom` row
    as needed.

    A plain function, not a method on
    :py:class:`~matrix_jitsi_bot.db.models.jitsi.JitsiInteraction`: once
    composed into
    :py:class:`~matrix_jitsi_bot.interactions.all.AllInteractions` (see
    :py:class:`~matrix_jitsi_bot.bot.MatrixJitsiBot`), a reaction's
    wrapped method runs with whichever interaction is actually
    dispatching as ``self`` - not necessarily a
    :py:class:`~matrix_jitsi_bot.db.models.jitsi.JitsiInteraction` - so
    a ``self._track(...)`` call would fail with an
    :py:exc:`AttributeError` there.

    Raises
    :py:exc:`~matrix_jitsi_bot.db.models.jitsi.RoomReferenceNotFound`
    if ``ref`` is given but isn't a full URL and doesn't resolve, or
    :py:exc:`~matrix_jitsi_bot.interactions.base.CommandError` if
    ``ref`` is a new URL containing
    :py:data:`~matrix_jitsi_bot.jitsi.NO_BOT_MARKER` - the same opt-out
    a Matrix room name uses, see
    :py:func:`~matrix_jitsi_bot.bot._register_room_on_invite` - or one
    that doesn't check out as an actual, reachable Jitsi conference at
    all, see
    :py:func:`~matrix_jitsi_bot.db.models.jitsi._verify_new_jitsi_room`.
    """
    if ref is not None and ref.startswith(("http://", "https://")):
        if opts_out_of_bot(ref):
            raise CommandError(
                f'Can\'t track {ref}: its URL contains "{NO_BOT_MARKER}", '
                "opting it out of the bot."
            )
        if not JitsiRoom.objects.filter(url=ref).exists():
            _verify_new_jitsi_room(ref)
        jitsi_room, _ = JitsiRoom.objects.get_or_create(url=ref)
    else:
        jitsi_room = _resolve_tracked_room(conversation.room, ref)

    tracked, _ = TrackedJitsiRoom.objects.get_or_create(
        room=conversation.room, jitsi_room=jitsi_room
    )
    for field in fields:
        tracked.set_track_field(field, value=True)
    tracked.save()
    return f"Now tracking {jitsi_room.url}."


def _untrack(conversation, ref: str | None, fields: tuple[str, ...] | None) -> str:
    """Undo tracking for ``ref``'s row in ``conversation``'s room.

    ``fields=None`` removes the row entirely, regardless of what it was
    tracking. Otherwise, clears just those fields - deleting the row
    anyway if nothing is left tracked, per
    :py:meth:`~matrix_jitsi_bot.db.models.jitsi.TrackedJitsiRoom.is_tracking_anything`.
    """
    try:
        jitsi_room = _resolve_tracked_room(conversation.room, ref)
    except RoomReferenceNotFound as exc:
        return str(exc)

    # `_resolve_tracked_room` only ever resolves to a conference this
    # room already has a `TrackedJitsiRoom` row for, so this is always
    # found - never `None`.
    tracked = TrackedJitsiRoom.objects.get(
        room=conversation.room, jitsi_room=jitsi_room
    )

    if fields is None:
        tracked.delete()
        return f"Stopped tracking {jitsi_room.url}."

    for field in fields:
        tracked.set_track_field(field, value=False)
    if not tracked.is_tracking_anything():
        tracked.delete()
        return f"Stopped tracking {jitsi_room.url}."
    tracked.save()
    return f"Updated tracking for {jitsi_room.url}."


class JitsiInteraction(BotInteraction):
    """Lets a room's Moderators track Jitsi conferences, and anyone check
    or query their status.
    """

    title = "Track a Jitsi conference"

    @Config(
        _TRACK,
        rf"track {_FLAG}{_ROOM}$",
        (
            "Track a Jitsi conference - what gets reported depends on "
            "the phrase used (moderators only). A URL tracked for the "
            "first time is checked right away; nothing is tracked if "
            "that check fails. Once a conference is tracked, its "
            "hostname or short name works as a shortcut for its full "
            "URL in any command."
        ),
        [
            "track status of https://meet.example.com/Room - open/close",
            "track open status of https://meet.example.com/Room - open only",
            "track close status of https://meet.example.com/Room - close only",
            "track who is in https://meet.example.com/Room - joins and leaves",
            "track who joins https://meet.example.com/Room - joins only",
            "track who leaves https://meet.example.com/Room - leaves only",
            "track who starts https://meet.example.com/Room - who's there on open",
            "track who starts Room - same, using the short name shortcut",
            "track who starts meet.example.com - same, using the hostname shortcut",
        ],
    )
    def react_to_track(self, flag: str, room: str | None) -> str:
        """Start tracking a conference, or add to what's already tracked
        about one - which fields ``flag`` sets is given by
        :py:data:`~matrix_jitsi_bot.db.models.jitsi._FLAG_FIELDS`.

        ``room`` is a full URL (creating the conference if it's new
        here - verified first, see
        :py:func:`~matrix_jitsi_bot.db.models.jitsi._verify_new_jitsi_room`),
        or - for one already tracked in this room - its hostname, its
        short name, or omitted entirely if exactly one conference is
        already tracked here; see
        :py:func:`~matrix_jitsi_bot.db.models.jitsi._resolve_tracked_room`.
        """
        return _track(self.conversation, room, _FLAG_FIELDS[flag])

    @Config(
        _UNTRACK_FLAG,
        rf"(?:don'?t|do not) track {_FLAG}{_ROOM}$",
        (
            "Stop tracking one aspect of a conference, keeping the "
            "rest (moderators only). The room can be a hostname or "
            "short name shortcut too, or omitted if only one is "
            "tracked here."
        ),
        [
            "don't track who joins https://meet.example.com/Room",
            "do not track open status of Room - using the short name shortcut",
        ],
    )
    def react_to_untrack_flag(self, flag: str, room: str | None) -> str:
        """Undo one
        :py:meth:`~matrix_jitsi_bot.db.models.jitsi.JitsiInteraction.react_to_track`
        flag - removing the conference from this room's tracking
        entirely once nothing is left set, per
        :py:func:`~matrix_jitsi_bot.db.models.jitsi._untrack`.
        """
        return _untrack(self.conversation, room, _FLAG_FIELDS[flag])

    @Config(
        _UNTRACK_ANY,
        r"(?:don'?t|do not) track any$",
        "Stop tracking every Jitsi conference in this room (moderators only).",
        ["don't track any - stops tracking everything here"],
    )
    def react_to_untrack_any(self) -> str:
        """Stop tracking every Jitsi conference tracked in this room.

        Registered with a lower ``id`` than
        :py:meth:`~matrix_jitsi_bot.db.models.jitsi.JitsiInteraction.react_to_untrack_one`,
        whose bare-room pattern would otherwise also match this message
        (parsing "any" as a room reference) - see that method's
        docstring.
        """
        TrackedJitsiRoom.objects.filter(room=self.conversation.room).delete()
        return "Stopped tracking every conference in this room."

    @Config(
        _UNTRACK_ONE,
        rf"(?:don'?t|do not) track{_ROOM}$",
        (
            "Stop tracking one Jitsi conference entirely (moderators "
            "only). The room can be a hostname or short name shortcut "
            "too, or omitted if only one is tracked here."
        ),
        [
            "don't track https://meet.example.com/Room - stops tracking it",
            "don't track Room - same, using the short name shortcut",
            "don't track - stops tracking the only tracked conference here",
        ],
    )
    def react_to_untrack_one(self, room: str | None) -> str:
        """Stop tracking one Jitsi conference entirely, however it was
        being tracked.

        Every flag phrase (see
        :py:data:`~matrix_jitsi_bot.db.models.jitsi._FLAG_FIELDS`) is a
        multi-word phrase, so it can never be mistaken for a single-word
        room reference here - except ``"any"``, handled instead by
        :py:meth:`~matrix_jitsi_bot.db.models.jitsi.JitsiInteraction.react_to_untrack_any`,
        registered with a lower ``id`` so it's tried first.
        """
        return _untrack(self.conversation, room, None)

    @Mention(
        _CHECK,
        rf"check{_ROOM}$",
        (
            "Check a tracked conference, or all of them, right now. "
            "The room can be a hostname or short name shortcut too."
        ),
        [
            "check - refreshes and reports every tracked conference "
            "(at most every few seconds)",
            "check Room - refreshes and reports just that one, using "
            "the short name shortcut",
        ],
    )
    def react_to_check(self, room: str | None = None) -> str:
        """Check ``room`` (or, if omitted, every conference tracked in
        this room), and report each one's status. Rate-limited per
        conference to at most once every
        :py:data:`~matrix_jitsi_bot.jitsi.MANUAL_CHECK_COOLDOWN` - a
        conference checked more recently than that is just reported
        from the database instead of being checked again.
        """
        import asyncio

        from matrix_jitsi_bot.jitsi import MANUAL_CHECK_COOLDOWN, check_jitsi_room

        if room is None:
            tracked = list(
                TrackedJitsiRoom.objects.filter(
                    room=self.conversation.room
                ).select_related("jitsi_room")
            )
            if not tracked:
                return "Nothing is being tracked in this room."
            jitsi_rooms = [entry.jitsi_room for entry in tracked]
        else:
            try:
                jitsi_rooms = [_resolve_tracked_room(self.conversation.room, room)]
            except RoomReferenceNotFound as exc:
                return str(exc)

        now = timezone.now()
        lines = []
        for jitsi_room in jitsi_rooms:
            due = (
                jitsi_room.last_checked_at is None
                or now - jitsi_room.last_checked_at >= MANUAL_CHECK_COOLDOWN
            )
            if due:
                status = asyncio.run(
                    check_jitsi_room(
                        jitsi_room.url,
                        want_participants=jitsi_room.wants_participants_check(),
                    )
                )
                jitsi_room.apply_status(status)
            lines.append(jitsi_room.describe())
        return "\n".join(lines)

    @Mention(
        _STATUS,
        r"status$",
        "List every conference tracked in this room and its last-known status.",
        ["status - from the database only, no network"],
    )
    def react_to_status(self) -> str:
        """List every conference tracked in this room with its
        last-known status, read from the database only - this performs
        no network check, unlike
        :py:meth:`~matrix_jitsi_bot.db.models.jitsi.JitsiInteraction.react_to_check`.
        """
        tracked = list(
            TrackedJitsiRoom.objects.filter(room=self.conversation.room).select_related(
                "jitsi_room"
            )
        )
        if not tracked:
            return "Nothing is being tracked in this room."
        return "\n".join(entry.jitsi_room.describe() for entry in tracked)
