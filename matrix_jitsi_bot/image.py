"""Getting an image from the web, e.g. for an account's avatar - see
:py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.set_account_avatar`.
"""

from __future__ import annotations

import functools
import io
import mimetypes
import re
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlparse

#: Bigger images are not downloaded - an avatar is small.
MAX_IMAGE_BYTES = 10_000_000

#: How long, in seconds, a download may take.
DOWNLOAD_TIMEOUT = 30


#: The side length in pixels of the avatar the bot discloses in a Jitsi
#: conference - it is shown small, and sent to everyone in the room.
JITSI_AVATAR_SIZE = 128


class DownloadFailed(Exception):
    """The image could not be downloaded - the message says why."""


def is_url(text: str) -> bool:
    """Whether ``text`` is a web address rather than a file path."""
    return text.startswith(("http://", "https://"))


def _file_name(url: str, content_type: str) -> str:
    """A safe file name for the image at ``url``, ending in what its
    ``content_type`` says.
    """
    name = Path(unquote(urlparse(url).path)).name
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name).strip(".") or "avatar"
    suffix = mimetypes.guess_extension(content_type)
    if suffix and Path(name).suffix.lower() != suffix:
        name = Path(name).stem + suffix
    return name


async def download_image(url: str, directory: Path) -> Path:
    """Download the image at ``url`` into ``directory`` and return its path.

    The file is named after the end of the address, with the ending
    that the server's content type says it has.

    Raises:
        DownloadFailed: the server could not be reached or answers
            with something else than an image, or the image is bigger
            than :py:data:`~matrix_jitsi_bot.image.MAX_IMAGE_BYTES`.
    """
    import asyncio

    import aiohttp

    timeout = aiohttp.ClientTimeout(total=DOWNLOAD_TIMEOUT)
    try:
        async with (
            aiohttp.ClientSession(timeout=timeout) as session,
            session.get(url) as response,
        ):
            if response.status != 200:
                raise DownloadFailed(f"{url}: the server answered {response.status}")
            content_type = response.content_type
            if not content_type.startswith("image/"):
                raise DownloadFailed(f"{url} is not an image but {content_type}")
            data = await response.content.read(MAX_IMAGE_BYTES + 1)
    except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
        raise DownloadFailed(f"{url} could not be downloaded: {exc}") from exc
    if len(data) > MAX_IMAGE_BYTES:
        raise DownloadFailed(f"{url} is bigger than {MAX_IMAGE_BYTES} bytes")
    path = directory / _file_name(url, content_type)
    await asyncio.to_thread(path.write_bytes, data)
    return path


def shrink_avatar(image: bytes) -> bytes:
    """``image`` - any format Pillow reads - as an image small enough to
    be disclosed in a Jitsi conference: at most
    :py:data:`~matrix_jitsi_bot.image.JITSI_AVATAR_SIZE` pixels on a side
    and below the size ``inspect-jitsi`` allows. A PNG, or a JPEG if that
    is still too big.

    Raises:
        ValueError: ``image`` is no image Pillow reads.
    """
    from inspect_jitsi.xmpp.avatar import MAX_AVATAR_FILE_SIZE
    from PIL import Image, UnidentifiedImageError

    try:
        picture = Image.open(io.BytesIO(image))
        picture.load()
    except (UnidentifiedImageError, OSError) as exc:
        msg = "The avatar is not an image that can be read."
        raise ValueError(msg) from exc
    picture = picture.convert("RGBA")
    picture.thumbnail((JITSI_AVATAR_SIZE, JITSI_AVATAR_SIZE))
    result = io.BytesIO()
    picture.save(result, format="PNG", optimize=True)
    if result.tell() > MAX_AVATAR_FILE_SIZE:
        result = io.BytesIO()
        flat = Image.new("RGB", picture.size, "white")
        flat.paste(picture, mask=picture.getchannel("A"))
        flat.save(result, format="JPEG", quality=80)
    return result.getvalue()


def avatar_data_uri(image: bytes) -> str:
    """``image`` as the ``data:`` URI ``inspect-jitsi`` takes as the avatar
    to disclose when joining - it checks the type and the size.
    """
    import inspect_jitsi

    suffix = ".png" if image.startswith(b"\x89PNG") else ".jpg"
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / f"avatar{suffix}"
        path.write_bytes(image)
        return inspect_jitsi.avatar_data_uri(path)


@functools.cache
def logo_avatar_url() -> str:
    """The logo of matrix-jitsi-bot as the avatar to disclose in a Jitsi
    conference - for an account that has none of its own.
    """
    import inspect_jitsi

    from .icon import LOGO_PNG

    return inspect_jitsi.avatar_data_uri(LOGO_PNG)
