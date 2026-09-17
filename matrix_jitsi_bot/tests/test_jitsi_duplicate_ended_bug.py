"""Regression test for a reported bug: a conference's "ended" message
got sent twice for what looked like one continuous session:

    Nicco Kunzmann started the conference at .../pycal
    Conference .../pycal ended
    Conference .../pycal ended

Root cause: `JitsiChange.messages_for` (matrix_jitsi_bot/jitsi.py) used
to gate "started" on `track_starts` only when `starters` was non-empty,
falling back to `track_open` - which this room didn't have set - for
an empty-starters reopen. So a brief, unannounced reopen (one whose
participant snapshot happened to come back empty) produced no visible
"started" line, while the close that followed it still got reported.
Two genuinely separate open/close cycles ended up looking like a
single conference being closed twice.

Fixed by always announcing "Conference <url> started" for a tracker
with `track_starts` set, even when the participant snapshot on that
particular poll came back empty - the same plain message `track_open`
alone would have produced. Every "ended" now has a visible "started"
paired with it.
"""

import asyncio
from unittest.mock import AsyncMock, call

from matrix_jitsi_bot.db.models import JitsiRoom, Room, TrackedJitsiRoom
from matrix_jitsi_bot.jitsi import JitsiStatus

URL = "https://meet.hosted.quelltext.eu/pycal"


def test_ended_is_no_longer_reported_twice_around_a_brief_reopen(monkeypatch) -> None:
    """track_starts + track_close, without track_open - the tracking
    configuration implied by the reported log (a "started the
    conference at ..." line, which only `track_starts` produces).
    """
    jitsi_room = JitsiRoom.objects.create(url=URL)
    chat_room = Room.objects.create(room_id="!pycal:example.org")
    TrackedJitsiRoom.objects.create(
        room=chat_room, jitsi_room=jitsi_room, track_starts=True, track_close=True
    )

    statuses = iter(
        [
            JitsiStatus(is_open=True, participants=["Nicco Kunzmann"]),
            JitsiStatus(is_open=False, participants=[]),
            JitsiStatus(is_open=True, participants=[]),  # brief reopen
            JitsiStatus(is_open=False, participants=[]),
        ]
    )

    async def _fake_check(url, *, want_participants, name=None):
        return next(statuses)

    monkeypatch.setattr("matrix_jitsi_bot.jitsi.check_jitsi_room", _fake_check)

    client = AsyncMock()
    for _ in range(4):
        asyncio.run(jitsi_room.check_and_notify(client))

    assert client.send_message.await_args_list == [
        call(chat_room.room_id, f"Nicco Kunzmann started the conference at {URL}"),
        call(chat_room.room_id, f"Conference {URL} ended"),
        call(chat_room.room_id, f"Conference {URL} started"),
        call(chat_room.room_id, f"Conference {URL} ended"),
    ]
