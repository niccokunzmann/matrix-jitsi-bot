"""Helpers for verifying Matrix Jitsi Bot account credentials against a homeserver,
and for setting the account's Matrix profile (display name, avatar).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from nio import (
    AsyncClient,
    LoginError,
    ProfileSetAvatarError,
    ProfileSetDisplayNameError,
    UploadError,
    WhoamiError,
)

if TYPE_CHECKING:
    from pathlib import Path


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


async def _authenticate(
    client: AsyncClient,
    *,
    user_id: str,
    password: str,
    access_token: str,
    device_id: str,
) -> None:
    """Authenticate ``client`` as ``user_id``, preferring ``access_token``
    if given - shared by
    :py:func:`~matrix_jitsi_bot.matrix_login.set_display_name` and
    :py:func:`~matrix_jitsi_bot.matrix_login.set_avatar`.

    An access token is trusted as-is, same as
    :py:func:`~matrix_jitsi_bot.matrix_login.check_login` does before
    using one; a password login is verified here too, raising
    :py:exc:`~matrix_jitsi_bot.matrix_login.LoginFailed` if the
    homeserver rejects it.
    """
    if access_token:
        client.access_token = access_token
        client.user_id = user_id
        if device_id:
            client.device_id = device_id
        return
    response = await client.login(password=password, device_name="matrix-jitsi-bot")
    if isinstance(response, LoginError):
        raise LoginFailed(f"{response.status_code}: {response.message}")


async def set_display_name(
    *,
    homeserver: str,
    user_id: str,
    password: str = "",
    access_token: str = "",
    device_id: str = "",
    display_name: str,
) -> None:
    """Set the Matrix account's profile display name - what most
    clients (Element included) insert as the leading word of a message
    when the account is mentioned via autocomplete, so this also
    affects what
    :py:attr:`~matrix_jitsi_bot.interactions.base.BotInteraction.bot_names`
    accepts as addressing the bot.

    Raises
    :py:exc:`~matrix_jitsi_bot.matrix_login.LoginFailed` if the
    homeserver rejects the credentials or the request.
    """
    client = AsyncClient(homeserver, user_id)
    try:
        await _authenticate(
            client,
            user_id=user_id,
            password=password,
            access_token=access_token,
            device_id=device_id,
        )
        response = await client.set_displayname(display_name)
        if isinstance(response, ProfileSetDisplayNameError):
            raise LoginFailed(f"{response.status_code}: {response.message}")
    finally:
        await client.close()


async def set_avatar(
    *,
    homeserver: str,
    user_id: str,
    password: str = "",
    access_token: str = "",
    device_id: str = "",
    image_path: Path,
) -> None:
    """Upload ``image_path`` and set it as the Matrix account's profile
    avatar ("logo").

    Raises
    :py:exc:`~matrix_jitsi_bot.matrix_login.LoginFailed` if the
    homeserver rejects the credentials, the upload, or the request.
    """
    import asyncio
    import mimetypes

    client = AsyncClient(homeserver, user_id)
    try:
        await _authenticate(
            client,
            user_id=user_id,
            password=password,
            access_token=access_token,
            device_id=device_id,
        )
        content_type = (
            mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
        )
        # Blocking filesystem I/O - off the event loop, same as
        # `matrix_jitsi_bot.jitsi.check_jitsi_room` does for its own
        # blocking calls.
        filesize = await asyncio.to_thread(lambda: image_path.stat().st_size)
        upload_response, _ = await client.upload(
            image_path,
            content_type=content_type,
            filename=image_path.name,
            filesize=filesize,
        )
        if isinstance(upload_response, UploadError):
            raise LoginFailed(
                f"{upload_response.status_code}: {upload_response.message}"
            )
        response = await client.set_avatar(upload_response.content_uri)
        if isinstance(response, ProfileSetAvatarError):
            raise LoginFailed(f"{response.status_code}: {response.message}")
    finally:
        await client.close()


async def has_cross_signing(
    *,
    homeserver: str,
    user_id: str,
    password: str = "",
    access_token: str = "",
    device_id: str = "",
) -> bool:
    """Whether ``user_id``'s account has a cross-signing identity set up
    on its homeserver at all - a ``self_signing_key`` published via
    ``POST /keys/query``, see
    https://spec.matrix.org/latest/client-server-api/#post_matrixclientv3keysquery.

    If this is ``False``, every device on the account - including
    whichever one the bot itself logs in as - will always show as "not
    verified by its owner" in every other user's client, regardless of
    anything the bot does: cross-signing has to be set up once, from
    an ordinary Matrix client logged in as this account (e.g.
    Element's Settings > Security & Privacy > "Set up encryption") -
    ``matrix-nio`` (which this bot is built on) has no cross-signing
    support at all, so the bot can't do this itself, only report on
    it - see
    :py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.check_account_cross_signing`.

    A raw HTTP request, deliberately bypassing
    :py:meth:`nio.AsyncClient.keys_query`: that requires a loaded
    encryption store and only queries users already known (from a
    prior sync) to need a key update, neither of which this quick,
    one-off check has - and its parsed
    :py:class:`nio.responses.KeysQueryResponse` drops the
    cross-signing key fields entirely regardless, keeping only
    ``device_keys``.
    """
    import aiohttp

    client = AsyncClient(homeserver, user_id)
    try:
        await _authenticate(
            client,
            user_id=user_id,
            password=password,
            access_token=access_token,
            device_id=device_id,
        )
        url = f"{homeserver.rstrip('/')}/_matrix/client/v3/keys/query"
        async with (
            aiohttp.ClientSession() as session,
            session.post(
                url,
                headers={"Authorization": f"Bearer {client.access_token}"},
                json={"device_keys": {user_id: []}},
            ) as response,
        ):
            data = await response.json()
    finally:
        await client.close()
    return bool(data.get("self_signing_keys", {}).get(user_id))
