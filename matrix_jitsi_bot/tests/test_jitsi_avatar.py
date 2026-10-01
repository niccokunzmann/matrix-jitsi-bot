"""The avatar the bot discloses when it joins a Jitsi conference: the
Matrix profile avatar of the account it runs as, else the logo.
"""

import asyncio
import base64
import io
from unittest.mock import AsyncMock, MagicMock

import nio
import pytest
from PIL import Image

from matrix_jitsi_bot.bot import (
    MatrixJitsiBot,
    _refresh_own_avatar,
)
from matrix_jitsi_bot.db.models import Account, JitsiRoom, Room, TrackedJitsiRoom
from matrix_jitsi_bot.icon import LOGO_PNG
from matrix_jitsi_bot.image import avatar_data_uri, logo_avatar_url, shrink_avatar
from matrix_jitsi_bot.jitsi import JitsiStatus

_BOT = "@bot:example.org"
_URL = "https://meet.example.org/Room"
_MXC = "mxc://example.org/avatar"


def _png(size=(300, 200), color="red", *, noisy=False) -> bytes:
    image = Image.new("RGBA", size, color)
    if noisy:  # noise in every channel does not compress
        import os

        image = Image.frombytes("RGBA", size, os.urandom(size[0] * size[1] * 4))
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def _decode(uri: str) -> bytes:
    header, _, payload = uri.partition(",")
    assert header.endswith(";base64")
    return base64.b64decode(payload)


# -- the image ---------------------------------------------------------------


@pytest.mark.no_database
def test_an_avatar_is_shrunk_to_a_small_png() -> None:
    small = shrink_avatar(_png((600, 300)))
    image = Image.open(io.BytesIO(small))
    assert image.format == "PNG"
    assert image.size == (128, 64)  # the proportions stay


@pytest.mark.no_database
def test_a_small_avatar_is_not_made_bigger() -> None:
    assert Image.open(io.BytesIO(shrink_avatar(_png((40, 30))))).size == (40, 30)


@pytest.mark.no_database
def test_an_avatar_that_is_too_big_as_png_becomes_a_jpeg() -> None:
    from inspect_jitsi.xmpp.avatar import MAX_AVATAR_FILE_SIZE

    shrunk = shrink_avatar(_png((128, 128), noisy=True))

    assert Image.open(io.BytesIO(shrunk)).format == "JPEG"
    assert len(shrunk) <= MAX_AVATAR_FILE_SIZE


@pytest.mark.no_database
def test_something_that_is_no_image_is_refused() -> None:
    with pytest.raises(ValueError, match="not an image"):
        shrink_avatar(b"this is text")


@pytest.mark.no_database
def test_an_avatar_becomes_a_data_uri_for_jitsi() -> None:
    uri = avatar_data_uri(shrink_avatar(_png()))
    assert uri.startswith("data:image/png;base64,")
    assert Image.open(io.BytesIO(_decode(uri))).format == "PNG"


@pytest.mark.no_database
def test_the_logo_can_be_disclosed_as_an_avatar() -> None:
    uri = logo_avatar_url()
    assert uri.startswith("data:image/png;base64,")
    assert _decode(uri) == LOGO_PNG.read_bytes()
    assert logo_avatar_url() is uri  # made once


# -- the account ----------------------------------------------------------------


def test_an_account_without_avatar_discloses_the_logo() -> None:
    Account.objects.create(user_id=_BOT, homeserver="https://example.org")
    assert Account.jitsi_avatar_of(_BOT) == logo_avatar_url()


def test_an_unknown_account_discloses_the_logo() -> None:
    assert Account.jitsi_avatar_of("@nobody:example.org") == logo_avatar_url()


def test_an_account_with_avatar_discloses_it() -> None:
    account = Account.objects.create(user_id=_BOT, homeserver="https://example.org")
    account.update_avatar(_MXC, "data:image/png;base64,QQ==")
    assert Account.jitsi_avatar_of(_BOT) == "data:image/png;base64,QQ=="


def test_the_avatar_is_read_fresh_every_time() -> None:
    account = Account.objects.create(user_id=_BOT, homeserver="https://example.org")
    assert Account.jitsi_avatar_of(_BOT) == logo_avatar_url()
    Account.objects.filter(pk=account.pk).update(avatar_data_uri="data:x")  # elsewhere
    assert Account.jitsi_avatar_of(_BOT) == "data:x"


def test_an_avatar_is_saved_only_if_it_changed() -> None:
    account = Account.objects.create(user_id=_BOT, homeserver="https://example.org")
    account.update_avatar(_MXC, "data:a")
    Account.objects.filter(pk=account.pk).update(avatar_data_uri="changed elsewhere")

    account.update_avatar(_MXC, "data:a")  # as it knows it: nothing to save

    assert Account.objects.get(pk=account.pk).avatar_data_uri == "changed elsewhere"
    account.update_avatar(None, None)
    stored = Account.objects.get(pk=account.pk)
    assert (stored.avatar_mxc, stored.avatar_data_uri) == ("", "")


# -- joining a conference -------------------------------------------------------------


def _tracked_open_conference():
    account = Account.objects.create(
        user_id=_BOT, homeserver="https://example.org", display_name="Bot"
    )
    room = Room.objects.create(room_id="!room:example.org", account=account)
    jitsi_room = JitsiRoom.objects.create(url=_URL)
    TrackedJitsiRoom.objects.create(room=room, jitsi_room=jitsi_room, track_joins=True)
    return account, jitsi_room


def _recording_check(monkeypatch) -> list:
    calls = []

    async def _check(url, *, want_participants=True, name=None, avatar_url=None):
        calls.append({"name": name, "avatar_url": avatar_url})
        return JitsiStatus(is_open=False, participants=None)

    monkeypatch.setattr("matrix_jitsi_bot.jitsi.check_jitsi_room", _check)
    return calls


def test_a_check_discloses_the_logo_of_an_account_without_avatar(monkeypatch) -> None:
    _, jitsi_room = _tracked_open_conference()
    calls = _recording_check(monkeypatch)

    asyncio.run(
        jitsi_room.check_and_notify(MagicMock(user_id=_BOT, send_message=AsyncMock()))
    )

    assert calls == [{"name": "Bot", "avatar_url": logo_avatar_url()}]


def test_a_check_discloses_the_avatar_of_the_account(monkeypatch) -> None:
    account, jitsi_room = _tracked_open_conference()
    account.update_avatar(_MXC, "data:image/png;base64,QQ==")
    calls = _recording_check(monkeypatch)

    asyncio.run(
        jitsi_room.check_and_notify(MagicMock(user_id=_BOT, send_message=AsyncMock()))
    )

    assert calls == [{"name": "Bot", "avatar_url": "data:image/png;base64,QQ=="}]


def test_staying_in_a_conference_discloses_the_avatar_too(monkeypatch) -> None:
    account, jitsi_room = _tracked_open_conference()
    account.update_avatar(_MXC, "data:image/png;base64,QQ==")
    seen = []

    async def _monitor(url, *, name=None, avatar_url=None):
        seen.append({"name": name, "avatar_url": avatar_url})
        return
        yield

    monkeypatch.setattr("matrix_jitsi_bot.jitsi.monitor_jitsi_room", _monitor)

    asyncio.run(
        jitsi_room.monitor_and_notify(MagicMock(user_id=_BOT, send_message=AsyncMock()))
    )

    assert seen == [{"name": "Bot", "avatar_url": "data:image/png;base64,QQ=="}]


def test_a_manual_check_discloses_the_avatar_too(
    send_message, make_moderator, monkeypatch
) -> None:
    from matrix_jitsi_bot.interactions.chat_notification import (
        ChatNotificationInteraction,
    )

    account, _jitsi_room = _tracked_open_conference()
    account.update_avatar(_MXC, "data:image/png;base64,QQ==")
    calls = _recording_check(monkeypatch)
    conv = send_message(
        f"@bot: check {_URL}", room_id="!room:example.org", sender="@a:x"
    )

    ChatNotificationInteraction().react_to_matrix_message(conv)

    assert calls == [{"name": "Bot", "avatar_url": "data:image/png;base64,QQ=="}]


# -- following the profile of the account --------------------------------------------------


def _client(*, avatar=_MXC, image=None) -> AsyncMock:
    client = AsyncMock()
    client.user_id = _BOT
    client.get_avatar.return_value = nio.ProfileGetAvatarResponse(avatar)
    client.download.return_value = nio.MemoryDownloadResponse(
        image or _png(), "image/png", None
    )
    return client


@pytest.fixture
def account():
    return Account.objects.create(user_id=_BOT, homeserver="https://example.org")


def _sync(client, account):
    asyncio.run(MatrixJitsiBot.sync_own_avatar(client, account))


def test_the_profile_avatar_is_downloaded_shrunk_and_stored(account) -> None:
    client = _client(image=_png((400, 400)))

    _sync(client, account)

    client.download.assert_awaited_once_with(mxc=_MXC)
    account.refresh_from_db()
    assert account.avatar_mxc == _MXC
    assert Image.open(io.BytesIO(_decode(account.avatar_data_uri))).size == (128, 128)
    assert Account.jitsi_avatar_of(_BOT) == account.avatar_data_uri


def test_an_avatar_that_is_stored_already_is_not_downloaded_again(account) -> None:
    client = _client()
    _sync(client, account)
    client.download.reset_mock()

    _sync(client, account)

    client.download.assert_not_awaited()


def test_an_avatar_that_changed_is_downloaded_and_stored(account) -> None:
    _sync(_client(), account)
    before = Account.objects.get(pk=account.pk).avatar_data_uri

    _sync(_client(avatar="mxc://example.org/new", image=_png(color="blue")), account)

    account.refresh_from_db()
    assert account.avatar_mxc == "mxc://example.org/new"
    assert account.avatar_data_uri != before


def test_an_account_that_removes_its_avatar_discloses_the_logo_again(account) -> None:
    _sync(_client(), account)

    _sync(_client(avatar=None), account)

    account.refresh_from_db()
    assert (account.avatar_mxc, account.avatar_data_uri) == ("", "")
    assert Account.jitsi_avatar_of(_BOT) == logo_avatar_url()


def test_an_avatar_that_is_no_image_is_logged_and_the_logo_stays(
    account, caplog
) -> None:
    client = _client(image=b"not an image")

    with caplog.at_level("WARNING", logger="matrix_jitsi_bot.bot"):
        _sync(client, account)

    assert "cannot be shown in Jitsi" in caplog.text
    assert Account.jitsi_avatar_of(_BOT) == logo_avatar_url()


def test_what_is_stored_stays_if_the_profile_cannot_be_read(account, caplog) -> None:
    _sync(_client(), account)
    stored = Account.objects.get(pk=account.pk).avatar_data_uri
    client = _client()
    client.get_avatar.return_value = nio.ProfileGetAvatarError("down")

    with caplog.at_level("WARNING", logger="matrix_jitsi_bot.bot"):
        _sync(client, account)

    assert "Could not fetch this account's avatar" in caplog.text
    assert Account.objects.get(pk=account.pk).avatar_data_uri == stored


def test_a_failed_download_is_logged_and_nothing_changes(account, caplog) -> None:
    client = _client()
    client.download.return_value = nio.DownloadError("gone")

    with caplog.at_level("WARNING", logger="matrix_jitsi_bot.bot"):
        _sync(client, account)

    assert "Could not download the avatar" in caplog.text
    assert Account.objects.get(pk=account.pk).avatar_mxc == ""


def test_the_change_is_logged(account, caplog) -> None:
    with caplog.at_level("INFO", logger="matrix_jitsi_bot.bot"):
        _sync(_client(), account)
        _sync(_client(avatar=None), account)

    assert (
        f"{_BOT} discloses its profile avatar as its avatar in Jitsi" in caplog.text
        or (f"{_BOT} discloses its profile avatar" in caplog.text)
    )
    assert (
        f"{_BOT} discloses the logo as its avatar in Jitsi conferences" in caplog.text
    )


def _member_event(state_key: str, avatar_url):
    return MagicMock(state_key=state_key, content={"avatar_url": avatar_url})


def test_a_new_avatar_in_a_membership_event_is_followed(account) -> None:
    client = _client()

    asyncio.run(_refresh_own_avatar(client, account, _member_event(_BOT, _MXC)))

    account.refresh_from_db()
    assert account.avatar_mxc == _MXC


def test_a_membership_event_with_the_known_avatar_changes_nothing(account) -> None:
    client = _client()
    _sync(client, account)
    client.get_avatar.reset_mock()

    asyncio.run(_refresh_own_avatar(client, account, _member_event(_BOT, _MXC)))

    client.get_avatar.assert_not_awaited()


def test_the_membership_of_somebody_else_is_ignored(account) -> None:
    client = _client()

    asyncio.run(
        _refresh_own_avatar(client, account, _member_event("@other:example.org", _MXC))
    )

    client.get_avatar.assert_not_awaited()


# -- setting the avatar with the command line ------------------------------------------------


def test_setting_the_avatar_stores_it_for_jitsi_too(monkeypatch, tmp_path) -> None:
    account = Account.objects.create(
        user_id=_BOT, homeserver="https://example.org", password="secret"
    )
    image = tmp_path / "logo.png"
    image.write_bytes(_png((300, 300), "green"))

    async def _fake_set_avatar(**kwargs):
        return "mxc://example.org/set"

    monkeypatch.setattr("matrix_jitsi_bot.bot.set_avatar", _fake_set_avatar)

    asyncio.run(MatrixJitsiBot().set_account_avatar(_BOT, image))

    account.refresh_from_db()
    assert account.avatar_mxc == "mxc://example.org/set"
    assert Image.open(io.BytesIO(_decode(account.avatar_data_uri))).size == (128, 128)


def test_setting_a_file_that_is_no_image_still_sets_it_in_matrix(
    monkeypatch, tmp_path
) -> None:
    account = Account.objects.create(
        user_id=_BOT, homeserver="https://example.org", password="secret"
    )
    image = tmp_path / "logo.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")  # a header only
    uploaded = []

    async def _fake_set_avatar(**kwargs):
        uploaded.append(kwargs["image_path"])
        return "mxc://example.org/set"

    monkeypatch.setattr("matrix_jitsi_bot.bot.set_avatar", _fake_set_avatar)

    asyncio.run(MatrixJitsiBot().set_account_avatar(_BOT, image))

    assert uploaded == [image]
    account.refresh_from_db()
    assert account.avatar_data_uri == ""  # the logo is disclosed
    assert account.avatar_mxc == "mxc://example.org/set"
