"""Checking Jitsi conference status, and the outcome of applying one.

:py:func:`~matrix_jitsi_bot.jitsi.check_jitsi_room` is a thin, mockable
wrapper around ``inspect-jitsi`` - the rest of the bot calls it rather
than ``inspect_jitsi`` directly, so tests can substitute a fake status
without any network access. See
:py:meth:`~matrix_jitsi_bot.db.models.jitsi.JitsiRoom.apply_status` for
where a :py:class:`~matrix_jitsi_bot.jitsi.JitsiStatus` actually gets
applied.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from matrix_jitsi_bot.db.models import JitsiRoom, TrackedJitsiRoom

#: A manual
#: :py:meth:`~matrix_jitsi_bot.db.models.jitsi.JitsiInteraction.react_to_check`
#: is rate-limited to at most this often.
MANUAL_CHECK_COOLDOWN = timedelta(seconds=5)

#: The bot refuses to stay in - and immediately leaves - any Matrix
#: room whose name contains this, case-insensitively (see
#: :py:func:`~matrix_jitsi_bot.bot._register_room_on_invite`), and
#: refuses to track any Jitsi conference URL containing it too (see
#: :py:func:`~matrix_jitsi_bot.db.models.jitsi._track`). See
#: :doc:`/hosting-a-bot/index`.
NO_BOT_MARKER = "no-bot"


def opts_out_of_bot(text: str) -> bool:
    """Whether ``text`` (a room name or a Jitsi URL) contains
    :py:data:`~matrix_jitsi_bot.jitsi.NO_BOT_MARKER`, case-insensitively.
    """
    return NO_BOT_MARKER in text.lower()


@dataclass
class JitsiStatus:
    """A Jitsi conference's status, as just observed.

    ``participants`` is ``None`` when they weren't checked at all - see
    :py:func:`~matrix_jitsi_bot.jitsi.check_jitsi_room`'s
    ``want_participants`` argument and
    :py:meth:`~matrix_jitsi_bot.db.models.jitsi.JitsiRoom.wants_participants_check`
    for when that's the case - as opposed to ``[]``, which means they
    were checked and it's empty.
    """

    is_open: bool
    participants: list[str] | None
    attempts: int = 0
    """While monitoring: reconnect attempts since the connection was lost."""


async def check_jitsi_room(
    url: str, *, want_participants: bool = True, name: str | None = None
) -> JitsiStatus:
    """Check whether the Jitsi conference at ``url`` is open, and - if
    ``want_participants`` - who's in it.

    ``name`` - the bot's own Matrix account display name, if it has
    one (see
    :py:attr:`~matrix_jitsi_bot.db.models.account.Account.display_name`)
    - is disclosed as this probe's own display name while briefly
    joining to read the participant list. Ignored if
    ``want_participants`` is ``False``, since that skips joining
    entirely.

    ``inspect-jitsi``'s checks are synchronous, blocking network calls,
    so they run in a worker thread here, keeping the bot's own event
    loop free to handle other rooms and messages meanwhile.
    """
    is_open = await asyncio.to_thread(_is_room_created, url)
    if not is_open or not want_participants:
        return JitsiStatus(is_open=is_open, participants=None)
    participants = await asyncio.to_thread(_get_participant_names, url, name)
    return JitsiStatus(is_open=True, participants=participants)


async def monitor_jitsi_room(
    url: str, *, name: str | None = None
) -> AsyncIterator[JitsiStatus]:
    """Stay in the Jitsi conference at ``url`` and yield its
    :py:class:`~matrix_jitsi_bot.jitsi.JitsiStatus` every time it
    changes, until the conference is closed.

    The counterpart to
    :py:func:`~matrix_jitsi_bot.jitsi.check_jitsi_room` that keeps its
    connection alive - ``inspect-jitsi``'s ``monitor_conference`` -
    instead of joining briefly per check, so joins and leaves are seen
    the moment they happen. The last status yielded is a closed one;
    a conference that doesn't exist (yet) yields just that. ``name`` is
    disclosed as the monitor's own display name, like in
    :py:func:`~matrix_jitsi_bot.jitsi.check_jitsi_room`. Reconnecting
    after a lost connection is handled by ``inspect-jitsi``; if that
    fails, its ``JitsiConnectionError`` propagates. Closing this
    generator (e.g. by cancelling the task iterating it) leaves the
    conference.

    The conference counts as closed - and the monitor leaves it - as
    soon as the bot is the only one left in it. It has to: the bot's own
    presence would otherwise keep the conference open forever.
    """
    import inspect_jitsi

    states = inspect_jitsi.monitor_conference(url, name=name)
    try:
        async for state in states:
            yield JitsiStatus(
                is_open=state["status"]["open"],
                participants=[
                    participant.get("name") or participant["nick"]
                    for participant in state["participants"]
                ],
                attempts=state["status"]["attempts"],
            )
    finally:
        await states.aclose()


def _is_room_created(url: str) -> bool:
    """Whether the Jitsi conference at ``url`` currently has an open room."""
    import inspect_jitsi

    return inspect_jitsi.is_room_created(url)


def _get_participant_names(url: str, name: str | None) -> list[str]:
    """Names (or nicknames) of everyone currently in the Jitsi
    conference at ``url``, disclosing ``name`` as this probe's own
    display name while briefly joining.
    """
    import inspect_jitsi

    return [
        participant.name or participant.nick
        for participant in inspect_jitsi.get_participants(url, name=name)
    ]


@dataclass
class JitsiChange:
    """What changed about a
    :py:class:`~matrix_jitsi_bot.db.models.jitsi.JitsiRoom` between two
    checks - see
    :py:meth:`~matrix_jitsi_bot.db.models.jitsi.JitsiRoom.apply_status`,
    which builds one.

    Kept apart, rather than one combined flag, so a notification can
    respect each
    :py:class:`~matrix_jitsi_bot.db.models.jitsi.TrackedJitsiRoom`
    field independently - see
    :py:meth:`~matrix_jitsi_bot.jitsi.JitsiChange.messages_for`.
    ``starters`` is who was in the conference the moment it was noticed
    open (``None`` if not fetched, ``[]`` if fetched and empty) -
    distinct from ``joined``/``left``, which are only ever populated by
    a later check of an *already*-open conference, diffing against the
    previous participant list.
    """

    opened: bool
    closed: bool
    starters: list[str] | None
    joined: list[str]
    left: list[str]

    def __bool__(self) -> bool:
        """Whether anything changed at all."""
        return bool(
            self.opened or self.closed or self.starters or self.joined or self.left
        )

    def messages_for(
        self, jitsi_room: JitsiRoom, tracked: TrackedJitsiRoom
    ) -> list[str]:
        """The chat messages ``tracked`` should be told about this
        change - zero, one, or more lines, in the spec's wording
        (``"Conference <url> started"``, ``"<Name> joined <url>"``,
        etc.).

        On an opening, a tracker wanting ``track_starts`` gets the
        fuller "who started it" line instead of the plain "started"
        one whenever ``starters`` was actually fetched, so a tracker
        wanting both isn't told about the same opening twice.
        """
        url = jitsi_room.url
        lines = []
        if self.opened:
            if tracked.track_starts and self.starters is not None:
                if self.starters:
                    names = ", ".join(self.starters)
                    lines.append(f"{names} started the conference at {url}")
                else:
                    lines.append(f"Conference {url} started")
            elif tracked.track_open:
                lines.append(f"Conference {url} started")
        if self.closed and tracked.track_close:
            lines.append(f"Conference {url} ended")
        if tracked.track_joins:
            lines.extend(f"{name} joined {url}" for name in self.joined)
        if tracked.track_leaves:
            lines.extend(f"{name} left {url}" for name in self.left)
        return lines
