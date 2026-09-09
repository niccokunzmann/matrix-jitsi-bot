"""Helpers for verifying Matrix Jitsi Bot account credentials against a homeserver."""

from __future__ import annotations

from dataclasses import dataclass

from nio import AsyncClient, LoginError, WhoamiError


class LoginFailed(Exception):
    """Raised when Matrix credentials could not be verified against the homeserver."""


def homeserver_from_user_id(user_id: str) -> str:
    """Guess a homeserver URL from a Matrix user ID's server name.

    A user ID's server name (``@localpart:server_name``) isn't always
    the homeserver's actual client-server API address - a homeserver
    can delegate that to a different host via
    ``.well-known/matrix/client``, which this does not look up. It's a
    reasonable default, but wrong for a delegating homeserver; pass
    ``homeserver`` explicitly for those.

    Raises :py:exc:`ValueError` if ``user_id`` has no server name to
    guess from.
    """
    _, _, server_name = user_id.partition(":")
    if not server_name:
        raise ValueError(f"{user_id!r} is not a Matrix user ID (expected @user:server)")
    return f"https://{server_name}"


@dataclass
class LoginCheckResult:
    """The outcome of successfully verifying credentials against a Matrix homeserver."""

    message: str
    device_id: str = ""
    access_token: str = ""


async def check_login(
    *,
    homeserver: str,
    user_id: str,
    password: str = "",
    access_token: str = "",
    device_id: str = "",
) -> LoginCheckResult:
    """Verify Matrix credentials by contacting the homeserver.

    Prefers an access token (via ``whoami``) when one is given,
    otherwise logs in with the password. On a successful password
    login, the device ID and access token issued by the homeserver are
    returned so they can be stored for future token-based checks.

    Raises
    :py:exc:`~matrix_jitsi_bot.matrix_login.LoginFailed` if the
    homeserver rejects the credentials.
    """
    client = AsyncClient(homeserver, user_id)
    try:
        if access_token:
            client.access_token = access_token
            client.user_id = user_id
            if device_id:
                client.device_id = device_id
            response = await client.whoami()
            if isinstance(response, WhoamiError):
                raise LoginFailed(f"{response.status_code}: {response.message}")
            return LoginCheckResult(
                message=f"Logged in as {response.user_id}",
                device_id=device_id,
                access_token=access_token,
            )

        response = await client.login(password=password, device_name="matrix-jitsi-bot")
        if isinstance(response, LoginError):
            raise LoginFailed(f"{response.status_code}: {response.message}")
        return LoginCheckResult(
            message=f"Logged in as {response.user_id} (device_id={response.device_id})",
            device_id=response.device_id,
            access_token=response.access_token,
        )
    finally:
        await client.close()
