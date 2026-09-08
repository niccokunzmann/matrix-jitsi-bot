import pytest

from matrix_jitsi_bot.matrix_login import homeserver_from_user_id


def test_homeserver_from_user_id() -> None:
    assert homeserver_from_user_id("@bot:example.org") == "https://example.org"


def test_homeserver_from_user_id_keeps_port() -> None:
    assert (
        homeserver_from_user_id("@bot:example.org:8448") == "https://example.org:8448"
    )


def test_homeserver_from_user_id_rejects_malformed_id() -> None:
    with pytest.raises(ValueError, match="not a Matrix user ID"):
        homeserver_from_user_id("bot")
