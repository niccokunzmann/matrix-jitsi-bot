"""Downloading an image, e.g. for an avatar - and completing its path."""

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from typer.testing import CliRunner

from matrix_jitsi_bot import image as image_module
from matrix_jitsi_bot.cli import _complete_image, app
from matrix_jitsi_bot.image import DownloadFailed, download_image, is_url

_PNG = b"\x89PNG\r\n\x1a\n some picture"


@pytest.fixture
def server():
    """A web server on this machine, answering what ``routes`` says:
    a path to ``(status, content type, body, extra headers)``.
    """
    routes: dict = {
        "/logo.png": (200, "image/png", _PNG, {}),
        "/photo": (200, "image/jpeg", b"\xff\xd8 jpeg", {}),
        "/wrong.png": (200, "image/jpeg", b"\xff\xd8 jpeg", {}),
        "/page.html": (200, "text/html", b"<html></html>", {}),
        "/moved": (302, "text/plain", b"", {"Location": "/logo.png"}),
    }

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            status, content_type, body, headers = routes.get(
                self.path, (404, "text/plain", b"missing", {})
            )
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            for name, value in headers.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args) -> None:
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}", routes
    httpd.shutdown()
    httpd.server_close()


@pytest.mark.no_database
@pytest.mark.parametrize(
    ("text", "url"),
    [
        ("http://example.org/a.png", True),
        ("https://example.org/a.png", True),
        ("logo.png", False),
        ("/home/me/logo.png", False),
        ("docs/https://x.png", False),
    ],
)
def test_what_is_a_url(text, url) -> None:
    assert is_url(text) is url


@pytest.mark.no_database
def test_an_image_is_downloaded(server, tmp_path) -> None:
    base, _ = server

    path = asyncio.run(download_image(f"{base}/logo.png", tmp_path))

    assert path == tmp_path / "logo.png"
    assert path.read_bytes() == _PNG


@pytest.mark.no_database
def test_the_file_ending_comes_from_the_content_type(server, tmp_path) -> None:
    base, _ = server

    without_ending = asyncio.run(download_image(f"{base}/photo", tmp_path))
    wrong_ending = asyncio.run(download_image(f"{base}/wrong.png", tmp_path))

    assert without_ending.name == "photo.jpg"
    assert wrong_ending.name == "wrong.jpg"


@pytest.mark.no_database
def test_a_redirect_is_followed(server, tmp_path) -> None:
    base, _ = server

    path = asyncio.run(download_image(f"{base}/moved", tmp_path))

    assert path.read_bytes() == _PNG


@pytest.mark.no_database
def test_the_file_name_is_made_safe(server, tmp_path) -> None:
    base, routes = server
    routes["/a%20b/..%2F..%2Fevil.png"] = (200, "image/png", _PNG, {})

    path = asyncio.run(download_image(f"{base}/a%20b/..%2F..%2Fevil.png", tmp_path))

    assert path.parent == tmp_path
    assert path.name == "evil.png"


@pytest.mark.no_database
def test_something_that_is_no_image_is_not_downloaded(server, tmp_path) -> None:
    base, _ = server
    with pytest.raises(DownloadFailed, match="is not an image but text/html"):
        asyncio.run(download_image(f"{base}/page.html", tmp_path))
    assert not list(tmp_path.iterdir())


@pytest.mark.no_database
def test_a_missing_image_is_reported(server, tmp_path) -> None:
    base, _ = server
    with pytest.raises(DownloadFailed, match="the server answered 404"):
        asyncio.run(download_image(f"{base}/nothing.png", tmp_path))


@pytest.mark.no_database
def test_a_server_that_cannot_be_reached_is_reported(tmp_path) -> None:
    with pytest.raises(DownloadFailed, match="could not be downloaded"):
        asyncio.run(download_image("http://127.0.0.1:9/logo.png", tmp_path))


@pytest.mark.no_database
def test_an_image_that_is_too_big_is_not_downloaded(
    server, tmp_path, monkeypatch
) -> None:
    base, _ = server
    monkeypatch.setattr(image_module, "MAX_IMAGE_BYTES", 5)
    with pytest.raises(DownloadFailed, match="is bigger than 5 bytes"):
        asyncio.run(download_image(f"{base}/logo.png", tmp_path))
    assert not list(tmp_path.iterdir())


# -- the avatar command -------------------------------------------------------

runner = CliRunner()


def _account() -> None:
    result = runner.invoke(
        app,
        [
            "account",
            "create",
            "@bot:example.org",
            "--homeserver",
            "https://example.org",
            "--password",
            "secret",
            "--no-test",
        ],
    )
    assert result.exit_code == 0, result.output


def test_an_avatar_is_downloaded_from_a_url(server, monkeypatch) -> None:
    _account()
    base, _ = server
    uploads = []

    async def _fake_set_avatar(**kwargs):
        image = kwargs["image_path"]
        uploads.append((image.name, image.read_bytes()))  # while it still exists

    monkeypatch.setattr("matrix_jitsi_bot.bot.set_avatar", _fake_set_avatar)

    result = runner.invoke(
        app, ["account", "set", "avatar", "@bot:example.org", f"{base}/logo.png"]
    )

    assert result.exit_code == 0, result.output
    assert "Updated avatar" in result.output
    assert uploads == [("logo.png", _PNG)]


def test_the_downloaded_avatar_is_deleted_afterwards(server, monkeypatch) -> None:
    _account()
    base, _ = server
    paths = []

    async def _fake_set_avatar(**kwargs):
        paths.append(kwargs["image_path"])

    monkeypatch.setattr("matrix_jitsi_bot.bot.set_avatar", _fake_set_avatar)

    runner.invoke(
        app, ["account", "set", "avatar", "@bot:example.org", f"{base}/logo.png"]
    )

    assert not paths[0].exists()
    assert not paths[0].parent.exists()


def test_an_avatar_url_that_is_no_image_is_reported(server, monkeypatch) -> None:
    _account()
    base, _ = server
    calls = []

    async def _fake_set_avatar(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr("matrix_jitsi_bot.bot.set_avatar", _fake_set_avatar)

    result = runner.invoke(
        app, ["account", "set", "avatar", "@bot:example.org", f"{base}/page.html"]
    )

    assert result.exit_code == 1
    assert "is not an image but text/html" in result.output
    assert calls == []


# -- completion ----------------------------------------------------------------


@pytest.fixture
def files(tmp_path, monkeypatch):
    for name in ("avatar1.png", "avatar2.jpg", "notes.txt", ".hidden"):
        (tmp_path / name).touch()
    (tmp_path / "pics").mkdir()
    (tmp_path / "pics" / "cat.png").touch()
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.mark.no_database
def test_the_files_and_directories_of_the_path_are_completed(files) -> None:
    assert _complete_image(None, None, "") == [
        "avatar1.png",
        "avatar2.jpg",
        "notes.txt",
        "pics/",
    ]
    assert _complete_image(None, None, "ava") == ["avatar1.png", "avatar2.jpg"]
    assert _complete_image(None, None, "avatar1") == ["avatar1.png"]


@pytest.mark.no_database
def test_a_path_in_a_directory_is_completed(files) -> None:
    assert _complete_image(None, None, "pics/") == ["pics/cat.png"]
    assert _complete_image(None, None, "pics/c") == ["pics/cat.png"]
    assert _complete_image(None, None, f"{files}/pi") == [f"{files}/pics/"]


@pytest.mark.no_database
def test_hidden_files_are_completed_only_when_asked_for(files) -> None:
    assert ".hidden" not in _complete_image(None, None, "")
    assert _complete_image(None, None, ".") == [".hidden"]


@pytest.mark.no_database
def test_the_home_directory_is_completed(files, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(files))
    assert _complete_image(None, None, "~/pi") == ["~/pics/"]


@pytest.mark.no_database
def test_nothing_is_completed_for_a_missing_directory_or_a_url(files) -> None:
    assert _complete_image(None, None, "nowhere/x") == []
    assert _complete_image(None, None, "https://example.org/l") == []
