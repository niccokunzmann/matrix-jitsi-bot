"""Chat notifications about Jitsi conferences: what a room tracks.

See :doc:`/using-a-bot/index` for the commands
:py:class:`~matrix_jitsi_bot.interactions.chat_notification.ChatNotificationInteraction`
implements. The helpers they share with other interactions are in
:py:mod:`matrix_jitsi_bot.interactions.jitsi`.
"""

from __future__ import annotations

from django.utils import timezone

from matrix_jitsi_bot.db.models import Account, JitsiMonitor, TrackedJitsiRoom

from .base import BotInteraction, Config, Mention
from .jitsi import (
    _ROOM,
    RoomReferenceNotFound,
    _resolve_tracked_room,
    _track,
    _untrack,
)

#: The chat phrase following "track"/"don't track", to the
#: :py:data:`~matrix_jitsi_bot.db.models.jitsi._TRACK_FIELDS` it sets -
#: see :py:func:`~matrix_jitsi_bot.interactions.jitsi._track` and
#: :py:func:`~matrix_jitsi_bot.interactions.jitsi._untrack`.
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
#: reference) - see `ChatNotificationInteraction.react_to_untrack_any`.
_UNTRACK_ANY = 202
_UNTRACK_ONE = 203
_CHECK = 204
_STATUS = 205
_FLAG = (
    r"(?P<flag>status of|open status of|close status of"
    r"|who is in|who joins|who leaves|who starts)"
)


class ChatNotificationInteraction(BotInteraction):
    """Lets a room's Moderators choose what the bot reports in the chat
    about Jitsi conferences - opening, closing, who starts, joins and
    leaves - and lets anyone check or query their status.
    """

    title = "Chat notifications about a Jitsi conference"

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
        :py:data:`~matrix_jitsi_bot.interactions.chat_notification._FLAG_FIELDS`.

        ``room`` is a full URL (creating the conference if it's new
        here - verified first, see
        :py:func:`~matrix_jitsi_bot.interactions.jitsi._verify_new_jitsi_room`),
        or - for one already tracked in this room - its hostname, its
        short name, or omitted entirely if exactly one conference is
        already tracked here; see
        :py:func:`~matrix_jitsi_bot.interactions.jitsi._resolve_tracked_room`.
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
        :py:meth:`~matrix_jitsi_bot.interactions.chat_notification.ChatNotificationInteraction.react_to_track`
        flag - removing the conference from this room's tracking
        entirely once nothing is left set, per
        :py:func:`~matrix_jitsi_bot.interactions.jitsi._untrack`.
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
        :py:meth:`~matrix_jitsi_bot.interactions.chat_notification.ChatNotificationInteraction.react_to_untrack_one`,
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
        :py:data:`~matrix_jitsi_bot.interactions.chat_notification._FLAG_FIELDS`) is a
        multi-word phrase, so it can never be mistaken for a single-word
        room reference here - except ``"any"``, handled instead by
        :py:meth:`~matrix_jitsi_bot.interactions.chat_notification.ChatNotificationInteraction.react_to_untrack_any`,
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

        # The account running this room, if any - its display name (see
        # `Account.display_name`) and avatar are disclosed below while checking.
        account = self.conversation.room.account
        display_name = (account.display_name if account else "") or None
        avatar = Account.jitsi_avatar_of(account.user_id) if account else None

        now = timezone.now()
        lines = []
        for jitsi_room in jitsi_rooms:
            due = (
                jitsi_room.last_checked_at is None
                or now - jitsi_room.last_checked_at >= MANUAL_CHECK_COOLDOWN
            )
            # A conference the bot is in is always up to date already -
            # joining it a second time would only show up as a participant.
            if due and not JitsiMonitor.is_active(jitsi_room):
                status = asyncio.run(
                    check_jitsi_room(
                        jitsi_room.url,
                        want_participants=jitsi_room.wants_participants_check(),
                        name=display_name,
                        avatar_url=avatar,
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
        :py:meth:`~matrix_jitsi_bot.interactions.chat_notification.ChatNotificationInteraction.react_to_check`.
        """
        tracked = list(
            TrackedJitsiRoom.objects.filter(room=self.conversation.room).select_related(
                "jitsi_room"
            )
        )
        if not tracked:
            return "Nothing is being tracked in this room."
        return "\n".join(entry.jitsi_room.describe() for entry in tracked)
