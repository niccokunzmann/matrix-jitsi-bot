"""Getting an image from the web, e.g. for an account's avatar - see
:py:meth:`~matrix_jitsi_bot.bot.MatrixJitsiBot.set_account_avatar`.
"""

from __future__ import annotations

import mimetypes
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

#: Bigger images are not downloaded - an avatar is small.
MAX_IMAGE_BYTES = 10_000_000

#: How long, in seconds, a download may take.
DOWNLOAD_TIMEOUT = 30


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
