from datetime import timedelta

import pytest
from django.utils import timezone

from matrix_jitsi_bot.db.models import JitsiRoom, Room, TrackedJitsiRoom
from matrix_jitsi_bot.jitsi import JitsiStatus


def test_due_lists_only_rooms_whose_next_check_has_passed() -> None:
    due = JitsiRoom.objects.create(
        url="https://meet.example.org/Due", next_check_at=timezone.now()
    )
    JitsiRoom.objects.create(
        url="https://meet.example.org/NotYet",
        next_check_at=timezone.now() + timedelta(minutes=5),
    )

    assert JitsiRoom.due() == [due]


def test_tracked_lists_only_rooms_with_a_tracker() -> None:
    tracked_room = JitsiRoom.objects.create(url="https://meet.example.org/Tracked")
    JitsiRoom.objects.create(url="https://meet.example.org/Untracked")
    chat_room = Room.objects.create(room_id="!room:example.org")
    TrackedJitsiRoom.objects.create(room=chat_room, jitsi_room=tracked_room)

    assert JitsiRoom.tracked() == [tracked_room]


def test_tracked_ignores_next_check_at() -> None:
    """Unlike `due`, `tracked` doesn't care whether a check is due -
    see `MatrixJitsiBot.poll_jitsi_rooms_all`.
    """
    jitsi_room = JitsiRoom.objects.create(
        url="https://meet.example.org/Room",
        next_check_at=timezone.now() + timedelta(minutes=5),
    )
    chat_room = Room.objects.create(room_id="!room:example.org")
    TrackedJitsiRoom.objects.create(room=chat_room, jitsi_room=jitsi_room)

    assert JitsiRoom.tracked() == [jitsi_room]


def test_hostname_and_short_name_reject_a_no_bot_url() -> None:
    from matrix_jitsi_bot.jitsi import opts_out_of_bot

    assert opts_out_of_bot("https://meet.example.org/no-bot-standup") is True
    assert opts_out_of_bot("https://meet.example.org/standup") is False


def test_set_track_field_sets_a_known_field() -> None:
    room = JitsiRoom.objects.create(url="https://meet.example.org/Room")
    chat_room = Room.objects.create(room_id="!room:example.org")
    tracked = TrackedJitsiRoom.objects.create(room=chat_room, jitsi_room=room)

    tracked.set_track_field("track_joins", value=True)

    assert tracked.track_joins is True


def test_set_track_field_rejects_an_unknown_field() -> None:
    room = JitsiRoom.objects.create(url="https://meet.example.org/Room")
    chat_room = Room.objects.create(room_id="!room:example.org")
    tracked = TrackedJitsiRoom.objects.create(room=chat_room, jitsi_room=room)
    created_at = tracked.created_at

    with pytest.raises(ValueError, match="created_at"):
        tracked.set_track_field("created_at", value=True)

    assert tracked.created_at == created_at


def test_is_tracking_anything() -> None:
    room = JitsiRoom.objects.create(url="https://meet.example.org/Room")
    chat_room = Room.objects.create(room_id="!room:example.org")
    tracked = TrackedJitsiRoom.objects.create(room=chat_room, jitsi_room=room)

    assert tracked.is_tracking_anything() is False

    tracked.track_leaves = True
    assert tracked.is_tracking_anything() is True


def test_next_check_interval_defaults_to_fastest_when_never_open() -> None:
    room = JitsiRoom.objects.create(url="https://meet.example.org/Room")

    assert room.next_check_interval() == 1


def test_next_check_interval_tiers_by_recency() -> None:
    room = JitsiRoom.objects.create(url="https://meet.example.org/Room")

    room.last_opened_at = timezone.now()
    assert room.next_check_interval() == 1

    room.last_opened_at = timezone.now() - timedelta(days=2)
    assert room.next_check_interval() == 5

    room.last_opened_at = timezone.now() - timedelta(days=10)
    assert room.next_check_interval() == 15

    room.last_opened_at = timezone.now() - timedelta(days=40)
    assert room.next_check_interval() == 60


def test_hostname_and_short_name() -> None:
    room = JitsiRoom.objects.create(
        url="https://meet.hosted.quelltext.eu/matrix-jitsi-bot"
    )

    assert room.hostname() == "meet.hosted.quelltext.eu"
    assert room.short_name() == "matrix-jitsi-bot"


def test_apply_status_reports_opening() -> None:
    room = JitsiRoom.objects.create(url="https://meet.example.org/Room")

    change = room.apply_status(JitsiStatus(is_open=True, participants=["Alice"]))

    assert change.opened is True
    assert change.closed is False
    assert change.starters == ["Alice"]
    assert change.joined == []
    assert change.left == []
    assert bool(change) is True
    room.refresh_from_db()
    assert room.is_open is True
    assert room.participants == ["Alice"]
    assert room.last_checked_at is not None
    assert room.last_opened_at is not None


def test_apply_status_reports_everyone_already_there_as_starters() -> None:
    """If several people are already in the conference the moment it's
    first noticed open, all of them are starters - not just one."""
    room = JitsiRoom.objects.create(url="https://meet.example.org/Room")

    change = room.apply_status(
        JitsiStatus(is_open=True, participants=["Alice", "Bob", "Carol"])
    )

    assert change.starters == ["Alice", "Bob", "Carol"]
    room.refresh_from_db()
    assert room.participants == ["Alice", "Bob", "Carol"]


def test_apply_status_reports_opening_without_participants() -> None:
    room = JitsiRoom.objects.create(url="https://meet.example.org/Room")

    change = room.apply_status(JitsiStatus(is_open=True, participants=None))

    assert change.opened is True
    assert change.starters is None
    assert bool(change) is True


def test_apply_status_reports_closing() -> None:
    room = JitsiRoom.objects.create(
        url="https://meet.example.org/Room",
        is_open=True,
        participants=["Alice"],
        last_opened_at=timezone.now(),
    )

    change = room.apply_status(JitsiStatus(is_open=False, participants=[]))

    assert change.opened is False
    assert change.closed is True
    room.refresh_from_db()
    assert room.is_open is False
    assert room.participants == []


def test_apply_status_reports_joined_and_left_while_already_open() -> None:
    room = JitsiRoom.objects.create(
        url="https://meet.example.org/Room",
        is_open=True,
        participants=["Alice"],
        last_opened_at=timezone.now(),
    )

    change = room.apply_status(JitsiStatus(is_open=True, participants=["Bob"]))

    assert change.opened is False
    assert change.starters is None
    assert change.joined == ["Bob"]
    assert change.left == ["Alice"]
    assert bool(change) is True
    room.refresh_from_db()
    assert room.participants == ["Bob"]


def test_apply_status_no_change_when_still_closed() -> None:
    room = JitsiRoom.objects.create(url="https://meet.example.org/Room", is_open=False)

    change = room.apply_status(JitsiStatus(is_open=False, participants=[]))

    assert bool(change) is False


def test_apply_status_no_change_same_participants_while_open() -> None:
    room = JitsiRoom.objects.create(
        url="https://meet.example.org/Room",
        is_open=True,
        participants=["Alice"],
        last_opened_at=timezone.now(),
    )

    change = room.apply_status(JitsiStatus(is_open=True, participants=["Alice"]))

    assert change.joined == []
    assert change.left == []
    assert bool(change) is False


def test_apply_status_ignores_unchecked_participants() -> None:
    room = JitsiRoom.objects.create(
        url="https://meet.example.org/Room",
        is_open=False,
        participants=["Alice"],
    )

    change = room.apply_status(JitsiStatus(is_open=True, participants=None))

    assert change.opened is True
    assert change.starters is None
    assert change.joined == []
    assert change.left == []
    room.refresh_from_db()
    assert room.participants == ["Alice"]


def test_describe_closed() -> None:
    room = JitsiRoom.objects.create(url="https://meet.example.org/Room", is_open=False)

    assert room.describe() == "https://meet.example.org/Room: closed"


def test_describe_open_empty() -> None:
    room = JitsiRoom.objects.create(url="https://meet.example.org/Room", is_open=True)

    assert room.describe() == "https://meet.example.org/Room: open, empty"


def test_describe_open_with_participants() -> None:
    room = JitsiRoom.objects.create(
        url="https://meet.example.org/Room", is_open=True, participants=["Alice", "Bob"]
    )

    assert room.describe() == "https://meet.example.org/Room: open, with Alice, Bob"


def test_wants_participants_check_false_when_no_tracker_wants_participants() -> None:
    room = JitsiRoom.objects.create(url="https://meet.example.org/Room", is_open=False)
    chat_room = Room.objects.create(room_id="!room:example.org")
    TrackedJitsiRoom.objects.create(room=chat_room, jitsi_room=room, track_open=True)

    assert room.wants_participants_check() is False


def test_wants_participants_check_false_when_tracker_is_paused() -> None:
    room = JitsiRoom.objects.create(url="https://meet.example.org/Room", is_open=False)
    chat_room = Room.objects.create(room_id="!room:example.org", paused=True)
    TrackedJitsiRoom.objects.create(room=chat_room, jitsi_room=room, track_starts=True)

    assert room.wants_participants_check() is False


def test_wants_participants_check_true_when_closed_and_starts_wanted() -> None:
    room = JitsiRoom.objects.create(url="https://meet.example.org/Room", is_open=False)
    chat_room = Room.objects.create(room_id="!room:example.org")
    TrackedJitsiRoom.objects.create(room=chat_room, jitsi_room=room, track_starts=True)

    assert room.wants_participants_check() is True


def test_wants_participants_check_true_when_closed_and_joins_or_leaves_wanted() -> None:
    room = JitsiRoom.objects.create(url="https://meet.example.org/Room", is_open=False)
    chat_room = Room.objects.create(room_id="!room:example.org")
    TrackedJitsiRoom.objects.create(room=chat_room, jitsi_room=room, track_joins=True)

    assert room.wants_participants_check() is True


def test_wants_participants_check_false_when_open_and_only_starts_wanted() -> None:
    """Starts is a one-shot snapshot, already taken on the check that
    found it open - it shouldn't cause further fetches while open.
    """
    room = JitsiRoom.objects.create(url="https://meet.example.org/Room", is_open=True)
    chat_room = Room.objects.create(room_id="!room:example.org")
    TrackedJitsiRoom.objects.create(room=chat_room, jitsi_room=room, track_starts=True)

    assert room.wants_participants_check() is False


def test_wants_participants_check_true_when_open_and_joins_or_leaves_wanted() -> None:
    room = JitsiRoom.objects.create(url="https://meet.example.org/Room", is_open=True)
    chat_room = Room.objects.create(room_id="!room:example.org")
    TrackedJitsiRoom.objects.create(room=chat_room, jitsi_room=room, track_leaves=True)

    assert room.wants_participants_check() is True


def test_check_and_notify_updates_and_notifies_trackers(monkeypatch) -> None:
    import asyncio
    from unittest.mock import AsyncMock

    jitsi_room = JitsiRoom.objects.create(url="https://meet.example.org/Room")
    chat_room = Room.objects.create(room_id="!room:example.org")
    TrackedJitsiRoom.objects.create(
        room=chat_room, jitsi_room=jitsi_room, track_open=True
    )

    async def _fake_check(url, *, want_participants):
        return JitsiStatus(is_open=True, participants=None)

    monkeypatch.setattr("matrix_jitsi_bot.jitsi.check_jitsi_room", _fake_check)

    client = AsyncMock()
    asyncio.run(jitsi_room.check_and_notify(client))

    jitsi_room.refresh_from_db()
    assert jitsi_room.is_open is True
    client.send_message.assert_awaited_once_with(
        "!room:example.org", "Conference https://meet.example.org/Room started"
    )


def test_check_and_notify_lists_everyone_present_as_starters(monkeypatch) -> None:
    """End-to-end: a check that finds the conference already open with
    several people in it reports all of them as having started it, not
    just one - the actual scenario reported (a room noticing an
    already-busy conference, not just a single early joiner)."""
    import asyncio
    from unittest.mock import AsyncMock

    jitsi_room = JitsiRoom.objects.create(url="https://meet.example.org/Room")
    chat_room = Room.objects.create(room_id="!room:example.org")
    TrackedJitsiRoom.objects.create(
        room=chat_room, jitsi_room=jitsi_room, track_starts=True
    )

    async def _fake_check(url, *, want_participants):
        assert want_participants is True
        return JitsiStatus(is_open=True, participants=["Alice", "Bob", "Carol"])

    monkeypatch.setattr("matrix_jitsi_bot.jitsi.check_jitsi_room", _fake_check)

    client = AsyncMock()
    asyncio.run(jitsi_room.check_and_notify(client))

    jitsi_room.refresh_from_db()
    assert jitsi_room.participants == ["Alice", "Bob", "Carol"]
    client.send_message.assert_awaited_once_with(
        "!room:example.org",
        "Alice, Bob, Carol started the conference at https://meet.example.org/Room",
    )


def test_check_and_notify_does_nothing_when_nothing_changed(monkeypatch) -> None:
    import asyncio
    from unittest.mock import AsyncMock

    jitsi_room = JitsiRoom.objects.create(
        url="https://meet.example.org/Room", is_open=False
    )
    chat_room = Room.objects.create(room_id="!room:example.org")
    TrackedJitsiRoom.objects.create(
        room=chat_room, jitsi_room=jitsi_room, track_open=True
    )

    async def _fake_check(url, *, want_participants):
        return JitsiStatus(is_open=False, participants=None)

    monkeypatch.setattr("matrix_jitsi_bot.jitsi.check_jitsi_room", _fake_check)

    client = AsyncMock()
    asyncio.run(jitsi_room.check_and_notify(client))

    client.send_message.assert_not_awaited()
