from matrix_jitsi_bot.db.models import JitsiInteraction, TrackedJitsiRoom

_URL = "https://meet.example.org/Room"
_URL2 = "https://meet.example.org/Other"


def test_track_status_requires_a_moderator(send_message) -> None:
    conv = send_message(f"@bot: track status of {_URL}", sender="@user:example.org")

    result = JitsiInteraction().react_to_matrix_message(conv)

    assert "only room moderators" in result.text


def test_track_refuses_a_no_bot_url(send_message, make_moderator) -> None:
    url = "https://meet.example.org/no-bot-standup"
    conv = send_message(f"@bot: track status of {url}", sender="@mod:example.org")
    make_moderator(conv, "@mod:example.org")

    result = JitsiInteraction().react_to_matrix_message(conv)

    assert "no-bot" in result.text
    assert result.reaction == "❌"
    assert not TrackedJitsiRoom.objects.filter(jitsi_room__url=url).exists()


def test_track_refuses_an_unreachable_or_invalid_url(
    send_message, make_moderator, monkeypatch
) -> None:
    """A URL tracked for the first time is checked right away - if
    that check fails (a typo, a non-Jitsi URL, an unreachable host,
    ...), nothing is tracked, and the reply says so rather than
    reporting success."""
    url = "https://example.org/not-actually-jitsi"

    async def _boom(_url, *, want_participants=True):
        raise ConnectionError("server rejected WebSocket connection: HTTP 404")

    monkeypatch.setattr("matrix_jitsi_bot.jitsi.check_jitsi_room", _boom)

    conv = send_message(f"@bot: track status of {url}", sender="@mod:example.org")
    make_moderator(conv, "@mod:example.org")

    result = JitsiInteraction().react_to_matrix_message(conv)

    assert "doesn't look like a valid" in result.text
    assert result.reaction == "❌"
    assert not TrackedJitsiRoom.objects.filter(jitsi_room__url=url).exists()
    from matrix_jitsi_bot.db.models import JitsiRoom

    assert not JitsiRoom.objects.filter(url=url).exists()


def test_track_does_not_recheck_an_already_tracked_url(
    send_message, make_moderator, monkeypatch
) -> None:
    """Adding a flag to a conference already tracked (anywhere) doesn't
    re-run the initial check - only ever done the first time a URL is
    seen at all, see `_verify_new_jitsi_room`."""
    from matrix_jitsi_bot.db.models import JitsiRoom

    JitsiRoom.objects.create(url=_URL)

    calls = []

    async def _record(_url, *, want_participants=True):
        calls.append(_url)
        from matrix_jitsi_bot.jitsi import JitsiStatus

        return JitsiStatus(is_open=False, participants=None)

    monkeypatch.setattr("matrix_jitsi_bot.jitsi.check_jitsi_room", _record)

    conv = send_message(f"@bot: track status of {_URL}", sender="@mod:example.org")
    make_moderator(conv, "@mod:example.org")

    JitsiInteraction().react_to_matrix_message(conv)

    assert calls == []


def test_track_status_sets_open_and_close(send_message, make_moderator) -> None:
    conv = send_message(f"@bot: track status of {_URL}", sender="@mod:example.org")
    make_moderator(conv, "@mod:example.org")

    result = JitsiInteraction().react_to_matrix_message(conv)

    assert result.text == f"Now tracking {_URL}."
    tracked = TrackedJitsiRoom.objects.get(jitsi_room__url=_URL)
    assert tracked.room == conv.room
    assert tracked.track_open is True
    assert tracked.track_close is True
    assert tracked.track_starts is False
    assert tracked.track_joins is False
    assert tracked.track_leaves is False


def test_track_open_status_only(send_message, make_moderator) -> None:
    conv = send_message(f"@bot: track open status of {_URL}", sender="@mod:example.org")
    make_moderator(conv, "@mod:example.org")

    JitsiInteraction().react_to_matrix_message(conv)

    tracked = TrackedJitsiRoom.objects.get(jitsi_room__url=_URL)
    assert tracked.track_open is True
    assert tracked.track_close is False


def test_track_close_status_only(send_message, make_moderator) -> None:
    conv = send_message(
        f"@bot: track close status of {_URL}", sender="@mod:example.org"
    )
    make_moderator(conv, "@mod:example.org")

    JitsiInteraction().react_to_matrix_message(conv)

    tracked = TrackedJitsiRoom.objects.get(jitsi_room__url=_URL)
    assert tracked.track_open is False
    assert tracked.track_close is True


def test_track_who_is_in_sets_joins_and_leaves_only(
    send_message, make_moderator
) -> None:
    """Per the spec, "who is in" means join + leave - not the open/close
    status, and not the one-shot "who started it" snapshot either.
    """
    conv = send_message(f"@bot: track who is in {_URL}", sender="@mod:example.org")
    make_moderator(conv, "@mod:example.org")

    JitsiInteraction().react_to_matrix_message(conv)

    tracked = TrackedJitsiRoom.objects.get(jitsi_room__url=_URL)
    assert tracked.track_joins is True
    assert tracked.track_leaves is True
    assert tracked.track_open is False
    assert tracked.track_close is False
    assert tracked.track_starts is False


def test_track_who_joins_only(send_message, make_moderator) -> None:
    conv = send_message(f"@bot: track who joins {_URL}", sender="@mod:example.org")
    make_moderator(conv, "@mod:example.org")

    JitsiInteraction().react_to_matrix_message(conv)

    tracked = TrackedJitsiRoom.objects.get(jitsi_room__url=_URL)
    assert tracked.track_joins is True
    assert tracked.track_leaves is False


def test_track_who_leaves_only(send_message, make_moderator) -> None:
    conv = send_message(f"@bot: track who leaves {_URL}", sender="@mod:example.org")
    make_moderator(conv, "@mod:example.org")

    JitsiInteraction().react_to_matrix_message(conv)

    tracked = TrackedJitsiRoom.objects.get(jitsi_room__url=_URL)
    assert tracked.track_joins is False
    assert tracked.track_leaves is True


def test_track_who_starts_only(send_message, make_moderator) -> None:
    conv = send_message(f"@bot: track who starts {_URL}", sender="@mod:example.org")
    make_moderator(conv, "@mod:example.org")

    JitsiInteraction().react_to_matrix_message(conv)

    tracked = TrackedJitsiRoom.objects.get(jitsi_room__url=_URL)
    assert tracked.track_starts is True
    assert tracked.track_open is False


def test_track_accumulates_flags_across_commands(send_message, make_moderator) -> None:
    conv = send_message(f"@bot: track status of {_URL}", sender="@mod:example.org")
    make_moderator(conv, "@mod:example.org")
    JitsiInteraction().react_to_matrix_message(conv)

    conv = send_message(f"@bot: track who starts {_URL}", sender="@mod:example.org")
    JitsiInteraction().react_to_matrix_message(conv)

    tracked = TrackedJitsiRoom.objects.get(jitsi_room__url=_URL)
    assert tracked.track_open is True
    assert tracked.track_close is True
    assert tracked.track_starts is True


def test_track_by_short_name_of_an_already_tracked_room(
    send_message, make_moderator
) -> None:
    conv = send_message(f"@bot: track status of {_URL}", sender="@mod:example.org")
    make_moderator(conv, "@mod:example.org")
    JitsiInteraction().react_to_matrix_message(conv)

    conv = send_message("@bot: track who starts Room", sender="@mod:example.org")
    result = JitsiInteraction().react_to_matrix_message(conv)

    assert result.text == f"Now tracking {_URL}."
    tracked = TrackedJitsiRoom.objects.get(jitsi_room__url=_URL)
    assert tracked.track_starts is True


def test_track_by_omitted_room_when_only_one_tracked(
    send_message, make_moderator
) -> None:
    conv = send_message(f"@bot: track status of {_URL}", sender="@mod:example.org")
    make_moderator(conv, "@mod:example.org")
    JitsiInteraction().react_to_matrix_message(conv)

    conv = send_message("@bot: track who starts", sender="@mod:example.org")
    result = JitsiInteraction().react_to_matrix_message(conv)

    assert result.text == f"Now tracking {_URL}."


def test_track_by_ambiguous_short_name_fails(send_message, make_moderator) -> None:
    conv = send_message(f"@bot: track status of {_URL}", sender="@mod:example.org")
    make_moderator(conv, "@mod:example.org")
    JitsiInteraction().react_to_matrix_message(conv)
    conv = send_message(
        "@bot: track status of https://other.example.org/Room",
        sender="@mod:example.org",
    )
    JitsiInteraction().react_to_matrix_message(conv)

    conv = send_message("@bot: track who starts Room", sender="@mod:example.org")
    result = JitsiInteraction().react_to_matrix_message(conv)

    assert "doesn't uniquely identify" in result.text
    assert _URL in result.text
    assert "other.example.org/Room" in result.text


def test_dont_track_flag_removes_only_that_flag(send_message, make_moderator) -> None:
    conv = send_message(f"@bot: track status of {_URL}", sender="@mod:example.org")
    make_moderator(conv, "@mod:example.org")
    JitsiInteraction().react_to_matrix_message(conv)

    conv = send_message(
        f"@bot: don't track open status of {_URL}", sender="@mod:example.org"
    )
    result = JitsiInteraction().react_to_matrix_message(conv)

    assert result.text == f"Updated tracking for {_URL}."
    tracked = TrackedJitsiRoom.objects.get(jitsi_room__url=_URL)
    assert tracked.track_open is False
    assert tracked.track_close is True


def test_do_not_track_flag_also_works(send_message, make_moderator) -> None:
    conv = send_message(f"@bot: track status of {_URL}", sender="@mod:example.org")
    make_moderator(conv, "@mod:example.org")
    JitsiInteraction().react_to_matrix_message(conv)

    conv = send_message(
        f"@bot: do not track open status of {_URL}", sender="@mod:example.org"
    )
    result = JitsiInteraction().react_to_matrix_message(conv)

    assert result.text == f"Updated tracking for {_URL}."


def test_dont_track_flag_removes_row_once_nothing_left_tracked(
    send_message, make_moderator
) -> None:
    conv = send_message(f"@bot: track who starts {_URL}", sender="@mod:example.org")
    make_moderator(conv, "@mod:example.org")
    JitsiInteraction().react_to_matrix_message(conv)

    conv = send_message(
        f"@bot: don't track who starts {_URL}", sender="@mod:example.org"
    )
    result = JitsiInteraction().react_to_matrix_message(conv)

    assert result.text == f"Stopped tracking {_URL}."
    assert not TrackedJitsiRoom.objects.filter(jitsi_room__url=_URL).exists()


def test_dont_track_removes_it_entirely(send_message, make_moderator) -> None:
    conv = send_message(f"@bot: track status of {_URL}", sender="@mod:example.org")
    make_moderator(conv, "@mod:example.org")
    JitsiInteraction().react_to_matrix_message(conv)

    conv = send_message(f"@bot: don't track {_URL}", sender="@mod:example.org")
    result = JitsiInteraction().react_to_matrix_message(conv)

    assert result.text == f"Stopped tracking {_URL}."
    assert not TrackedJitsiRoom.objects.filter(jitsi_room__url=_URL).exists()


def test_dont_track_with_nothing_tracked_says_so(send_message, make_moderator) -> None:
    conv = send_message(f"@bot: don't track {_URL}", sender="@mod:example.org")
    make_moderator(conv, "@mod:example.org")

    result = JitsiInteraction().react_to_matrix_message(conv)

    assert result.text == "Nothing is being tracked in this room."


def test_dont_track_unknown_url_lists_whats_tracked(
    send_message, make_moderator
) -> None:
    conv = send_message(f"@bot: track status of {_URL}", sender="@mod:example.org")
    make_moderator(conv, "@mod:example.org")
    JitsiInteraction().react_to_matrix_message(conv)

    conv = send_message(f"@bot: don't track {_URL2}", sender="@mod:example.org")
    result = JitsiInteraction().react_to_matrix_message(conv)

    assert f"Not tracking {_URL2}" in result.text
    assert _URL in result.text


def test_dont_track_any_removes_everything(send_message, make_moderator) -> None:
    conv = send_message(f"@bot: track status of {_URL}", sender="@mod:example.org")
    make_moderator(conv, "@mod:example.org")
    JitsiInteraction().react_to_matrix_message(conv)

    conv = send_message("@bot: don't track any", sender="@mod:example.org")
    JitsiInteraction().react_to_matrix_message(conv)

    assert not TrackedJitsiRoom.objects.filter(room=conv.room).exists()


def test_do_not_track_any_also_works(send_message, make_moderator) -> None:
    conv = send_message(f"@bot: track status of {_URL}", sender="@mod:example.org")
    make_moderator(conv, "@mod:example.org")
    JitsiInteraction().react_to_matrix_message(conv)

    conv = send_message("@bot: do not track any", sender="@mod:example.org")
    JitsiInteraction().react_to_matrix_message(conv)

    assert not TrackedJitsiRoom.objects.filter(room=conv.room).exists()


def test_status_with_nothing_tracked(send_message) -> None:
    conv = send_message("@bot: status")

    result = JitsiInteraction().react_to_matrix_message(conv)

    assert result.text == "Nothing is being tracked in this room."


def test_status_reads_only_from_the_database(
    send_message, make_moderator, monkeypatch
) -> None:
    """`status` must not perform a network check."""

    conv = send_message(f"@bot: track status of {_URL}", sender="@mod:example.org")
    make_moderator(conv, "@mod:example.org")
    JitsiInteraction().react_to_matrix_message(conv)

    async def _boom(url):
        raise AssertionError("status must not check the network")

    monkeypatch.setattr("matrix_jitsi_bot.jitsi.check_jitsi_room", _boom)

    conv = send_message("@bot: status")
    result = JitsiInteraction().react_to_matrix_message(conv)

    assert _URL in result.text
    assert "closed" in result.text


def test_check_refreshes_and_reports(send_message, make_moderator, monkeypatch) -> None:
    from matrix_jitsi_bot.jitsi import JitsiStatus

    conv = send_message(f"@bot: track status of {_URL}", sender="@mod:example.org")
    make_moderator(conv, "@mod:example.org")
    JitsiInteraction().react_to_matrix_message(conv)

    async def _fake_check(url, *, want_participants):
        assert url == _URL
        # Only status is tracked here, so participants shouldn't be fetched.
        assert want_participants is False
        return JitsiStatus(is_open=True, participants=None)

    monkeypatch.setattr("matrix_jitsi_bot.jitsi.check_jitsi_room", _fake_check)

    conv = send_message("@bot: check")
    result = JitsiInteraction().react_to_matrix_message(conv)

    assert result.text == f"{_URL}: open, empty"


def test_check_one_room_by_short_name(
    send_message, make_moderator, monkeypatch
) -> None:
    from matrix_jitsi_bot.jitsi import JitsiStatus

    conv = send_message(f"@bot: track status of {_URL}", sender="@mod:example.org")
    make_moderator(conv, "@mod:example.org")
    JitsiInteraction().react_to_matrix_message(conv)
    conv = send_message(f"@bot: track status of {_URL2}", sender="@mod:example.org")
    JitsiInteraction().react_to_matrix_message(conv)

    async def _fake_check(url, *, want_participants):
        assert url == _URL
        return JitsiStatus(is_open=True, participants=None)

    monkeypatch.setattr("matrix_jitsi_bot.jitsi.check_jitsi_room", _fake_check)

    conv = send_message("@bot: check Room")
    result = JitsiInteraction().react_to_matrix_message(conv)

    assert result.text == f"{_URL}: open, empty"


def test_check_unknown_room_reports_the_error(send_message, make_moderator) -> None:
    conv = send_message(f"@bot: track status of {_URL}", sender="@mod:example.org")
    make_moderator(conv, "@mod:example.org")
    JitsiInteraction().react_to_matrix_message(conv)

    conv = send_message("@bot: check nonexistent")
    result = JitsiInteraction().react_to_matrix_message(conv)

    assert "doesn't uniquely identify" in result.text


def test_check_is_rate_limited(send_message, make_moderator, monkeypatch) -> None:
    from matrix_jitsi_bot.jitsi import JitsiStatus

    conv = send_message(f"@bot: track status of {_URL}", sender="@mod:example.org")
    make_moderator(conv, "@mod:example.org")
    JitsiInteraction().react_to_matrix_message(conv)

    calls = []

    async def _fake_check(url, *, want_participants):
        calls.append(url)
        return JitsiStatus(is_open=True, participants=[] if want_participants else None)

    monkeypatch.setattr("matrix_jitsi_bot.jitsi.check_jitsi_room", _fake_check)

    conv = send_message("@bot: check")
    JitsiInteraction().react_to_matrix_message(conv)
    conv = send_message("@bot: check")
    JitsiInteraction().react_to_matrix_message(conv)

    assert len(calls) == 1


def test_check_with_nothing_tracked(send_message) -> None:
    conv = send_message("@bot: check")

    result = JitsiInteraction().react_to_matrix_message(conv)

    assert result.text == "Nothing is being tracked in this room."
