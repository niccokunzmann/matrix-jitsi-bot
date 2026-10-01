import pytest

from matrix_jitsi_bot.matrix_login import homeserver_from_user_id

pytestmark = pytest.mark.no_database  # no use of the database


def test_homeserver_from_user_id() -> None:
    assert homeserver_from_user_id("@bot:example.org") == "https://example.org"


def test_homeserver_from_user_id_keeps_port() -> None:
    assert (
        homeserver_from_user_id("@bot:example.org:8448") == "https://example.org:8448"
    )


def test_homeserver_from_user_id_rejects_malformed_id() -> None:
    with pytest.raises(ValueError, match="not a Matrix user ID"):
        homeserver_from_user_id("bot")


def test_set_avatar_uploads_the_image_as_a_file_object(tmp_path, monkeypatch) -> None:
    """``nio`` accepts a file object or a callable as the data of an
    upload - not a path, which it rejects with a ``TypeError``."""
    import asyncio
    from types import SimpleNamespace

    import nio
    from nio.client.async_client import SynchronousFile

    from matrix_jitsi_bot import matrix_login

    image = tmp_path / "logo.png"
    image.write_bytes(b"\x89PNG data")
    uploads = []

    class _Client:
        def __init__(self, *args) -> None:
            pass

        async def upload(self, data_provider, **kwargs):
            assert isinstance(data_provider, SynchronousFile)
            uploads.append((data_provider.read(), kwargs))
            return SimpleNamespace(content_uri="mxc://example.org/logo"), None

        async def set_avatar(self, uri):
            uploads.append(uri)
            return nio.ProfileSetAvatarResponse()

        async def close(self) -> None:
            pass

    async def _authenticate(client, **kwargs) -> None:
        pass

    monkeypatch.setattr(matrix_login, "AsyncClient", _Client)
    monkeypatch.setattr(matrix_login, "_authenticate", _authenticate)

    asyncio.run(
        matrix_login.set_avatar(
            homeserver="https://example.org",
            user_id="@bot:example.org",
            access_token="secret",
            image_path=image,
        )
    )

    data, kwargs = uploads[0]
    assert data == b"\x89PNG data"
    assert (kwargs["content_type"], kwargs["filename"]) == ("image/png", "logo.png")
    assert uploads[1] == "mxc://example.org/logo"
