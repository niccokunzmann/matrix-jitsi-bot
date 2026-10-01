from datetime import timedelta

import pytest
from django.utils import timezone

from matrix_jitsi_bot.db.models import JitsiRoom, Room, TrackedJitsiRoom
from matrix_jitsi_bot.jitsi import JitsiStatus

# The real one, captured before the autouse fixture in conftest replaces it.
from matrix_jitsi_bot.jitsi import monitor_jitsi_room as _real_monitor_jitsi_room


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


@pytest.mark.no_database
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

    async def _fake_check(url, *, want_participants, name=None):
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

    async def _fake_check(url, *, want_participants, name=None):
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

    async def _fake_check(url, *, want_participants, name=None):
        return JitsiStatus(is_open=False, participants=None)

    monkeypatch.setattr("matrix_jitsi_bot.jitsi.check_jitsi_room", _fake_check)

    client = AsyncMock()
    asyncio.run(jitsi_room.check_and_notify(client))

    client.send_message.assert_not_awaited()


@pytest.mark.no_database
def test_get_participant_names_discloses_the_given_name(monkeypatch) -> None:
    from matrix_jitsi_bot import jitsi

    captured = {}

    def _fake_get_participants(url, name=None):
        captured["url"] = url
        captured["name"] = name
        return []

    monkeypatch.setattr("inspect_jitsi.get_participants", _fake_get_participants)

    jitsi._get_participant_names("https://meet.example.org/Room", "Conference Bot")

    assert captured == {
        "url": "https://meet.example.org/Room",
        "name": "Conference Bot",
    }


@pytest.mark.no_database
def test_get_participant_names_discloses_no_name_by_default(monkeypatch) -> None:
    from matrix_jitsi_bot import jitsi

    captured = {}

    def _fake_get_participants(url, name=None):
        captured["name"] = name
        return []

    monkeypatch.setattr("inspect_jitsi.get_participants", _fake_get_participants)

    jitsi._get_participant_names("https://meet.example.org/Room", None)

    assert captured["name"] is None


def test_check_and_notify_discloses_the_running_accounts_display_name(
    monkeypatch,
) -> None:
    import asyncio
    from unittest.mock import AsyncMock

    from matrix_jitsi_bot.db.models import Account

    Account.objects.create(
        user_id="@bot:example.org",
        homeserver="https://example.org",
        display_name="Conference Bot",
    )
    jitsi_room = JitsiRoom.objects.create(url="https://meet.example.org/Room")
    captured = {}

    async def _fake_check(url, *, want_participants, name=None):
        captured["name"] = name
        return JitsiStatus(is_open=False, participants=None)

    monkeypatch.setattr("matrix_jitsi_bot.jitsi.check_jitsi_room", _fake_check)

    client = AsyncMock(user_id="@bot:example.org")
    asyncio.run(jitsi_room.check_and_notify(client))

    assert captured["name"] == "Conference Bot"


def test_check_and_notify_discloses_no_name_for_an_unconfigured_account(
    monkeypatch,
) -> None:
    import asyncio
    from unittest.mock import AsyncMock

    jitsi_room = JitsiRoom.objects.create(url="https://meet.example.org/Room")
    captured = {}

    async def _fake_check(url, *, want_participants, name=None):
        captured["name"] = name
        return JitsiStatus(is_open=False, participants=None)

    monkeypatch.setattr("matrix_jitsi_bot.jitsi.check_jitsi_room", _fake_check)

    client = AsyncMock(user_id="@unknown:example.org")
    asyncio.run(jitsi_room.check_and_notify(client))

    assert captured["name"] is None


def test_check_and_notify_discloses_no_name_when_the_account_has_none_set(
    monkeypatch,
) -> None:
    """Unlike an unconfigured account, this one exists - it's just never
    had a display name set (`Account.display_name` defaults to ``""``)
    - and should still join anonymously, exactly the same way.
    """
    import asyncio
    from unittest.mock import AsyncMock

    from matrix_jitsi_bot.db.models import Account

    Account.objects.create(user_id="@bot:example.org", homeserver="https://example.org")
    jitsi_room = JitsiRoom.objects.create(url="https://meet.example.org/Room")
    captured = {}

    async def _fake_check(url, *, want_participants, name=None):
        captured["name"] = name
        return JitsiStatus(is_open=False, participants=None)

    monkeypatch.setattr("matrix_jitsi_bot.jitsi.check_jitsi_room", _fake_check)

    client = AsyncMock(user_id="@bot:example.org")
    asyncio.run(jitsi_room.check_and_notify(client))

    assert captured["name"] is None


@pytest.mark.no_database
def test_monitor_jitsi_room_yields_statuses_and_leaves_at_the_end(monkeypatch) -> None:
    """`monitor_jitsi_room` stays in the conference
    names participants like `check_jitsi_room` does, and leaves at the end.
    """
    import asyncio

    import inspect_jitsi

    from matrix_jitsi_bot.jitsi import JitsiStatus

    calls = []
    closed = []

    def _state(open_, participants):
        return {"status": {"open": open_, "attempts": 0}, "participants": participants}

    async def _fake_monitor(url, **kwargs):
        calls.append((url, kwargs))
        try:
            yield _state(True, [{"nick": "abc", "name": "Alice"}, {"nick": "def"}])
            yield _state(False, [])
        finally:
            closed.append(True)

    monkeypatch.setattr(inspect_jitsi, "monitor_conference", _fake_monitor)

    async def _collect():
        return [
            s
            async for s in _real_monitor_jitsi_room(
                "https://meet.example.org/R", name="Bot"
            )
        ]

    assert asyncio.run(_collect()) == [
        JitsiStatus(is_open=True, participants=["Alice", "def"]),
        JitsiStatus(is_open=False, participants=[]),
    ]
    assert calls == [("https://meet.example.org/R", {"name": "Bot"})]
    assert closed == [True]
