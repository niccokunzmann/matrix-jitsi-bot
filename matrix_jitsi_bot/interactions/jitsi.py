"""What the tracking commands of Jitsi conferences have in common.

The helpers resolve a conference reference in a room and set or clear
what a room tracks. They are used by
:py:class:`~matrix_jitsi_bot.interactions.chat_notification.ChatNotificationInteraction`
and
:py:class:`~matrix_jitsi_bot.interactions.avatar.AvatarInteraction`.
See :py:mod:`matrix_jitsi_bot.db.models.jitsi` for the models they work
with.
"""

from __future__ import annotations

from collections import Counter

from matrix_jitsi_bot.db.models import JitsiRoom, Room, TrackedJitsiRoom
from matrix_jitsi_bot.jitsi import NO_BOT_MARKER, opts_out_of_bot

from .base import CommandError

_URL = r"https?://\S+"
#: A room reference: a full URL, a hostname, or a short name - see
#: :py:func:`~matrix_jitsi_bot.interactions.jitsi._resolve_tracked_room` -
#: or omitted entirely, in a named ``room`` group so it's ``None``
#: rather than missing from ``match.groupdict()``.
_ROOM = r"(?:\s+(?P<room>\S+))?"


class RoomReferenceNotFound(CommandError):
    """Raised by
    :py:func:`~matrix_jitsi_bot.interactions.jitsi._resolve_tracked_room`
    when a room reference doesn't identify exactly one tracked
    conference - its message is the chat reply to send.

    A :py:exc:`~matrix_jitsi_bot.interactions.base.CommandError`, so
    letting it propagate out of a
    :py:class:`~matrix_jitsi_bot.interactions.chat_notification.ChatNotificationInteraction`
    handler both replies with its message and reacts with ❌ - see
    that exception.
    """


def _describe_references(tracked: list[TrackedJitsiRoom]) -> str:
    """A bullet list of ``tracked`` conferences, each with its URL and -
    only where unique among ``tracked`` - its hostname and short name
    as usable shortcuts (see
    :py:func:`~matrix_jitsi_bot.interactions.jitsi._resolve_tracked_room`).
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
    :py:func:`~matrix_jitsi_bot.interactions.jitsi._describe_references`
    - or ``None``, which resolves only if exactly one conference is
    tracked here at all.

    Raises
    :py:exc:`~matrix_jitsi_bot.interactions.jitsi.RoomReferenceNotFound`
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
    :py:func:`~matrix_jitsi_bot.interactions.jitsi._track`.

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

    A plain function, not a method on an interaction in
    :py:mod:`matrix_jitsi_bot.interactions.chat_notification`: once
    composed into
    :py:class:`~matrix_jitsi_bot.interactions.all.AllInteractions` (see
    :py:class:`~matrix_jitsi_bot.bot.MatrixJitsiBot`), a reaction's
    wrapped method runs with whichever interaction is actually
    dispatching as ``self`` - not necessarily that one - so
    a ``self._track(...)`` call would fail with an
    :py:exc:`AttributeError` there.

    Raises
    :py:exc:`~matrix_jitsi_bot.interactions.jitsi.RoomReferenceNotFound`
    if ``ref`` is given but isn't a full URL and doesn't resolve, or
    :py:exc:`~matrix_jitsi_bot.interactions.base.CommandError` if
    ``ref`` is a new URL containing
    :py:data:`~matrix_jitsi_bot.jitsi.NO_BOT_MARKER` - the same opt-out
    a Matrix room name uses, see
    :py:func:`~matrix_jitsi_bot.bot._register_room_on_invite` - or one
    that doesn't check out as an actual, reachable Jitsi conference at
    all, see
    :py:func:`~matrix_jitsi_bot.interactions.jitsi._verify_new_jitsi_room`.
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
