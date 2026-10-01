"""Generate the example images of "Change the room avatar image" in the
documentation, from the logo, with the code the bot itself uses.

For a chat and for a space, each is shown as it is, and with the speaker
drawn on it while a conference is open - see
:py:class:`~matrix_jitsi_bot.icon.merge.RoomSpeaker` and
:py:class:`~matrix_jitsi_bot.icon.merge.SpaceSpeaker`. Run this after the
logo or the speaker changes - ``make avatar-examples`` - and commit the
images it writes to :file:`docs/_static/avatar-examples/`.

.. code-block:: shell

    uv run python docs/generate_avatar_examples.py
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

from matrix_jitsi_bot.icon import LOGO_PNG
from matrix_jitsi_bot.icon.merge import RoomSpeaker, SpaceSpeaker

#: Where the images are written.
OUTPUT = Path(__file__).parent / "_static" / "avatar-examples"

#: The side length in pixels of the images.
SIZE = 256

#: What the avatar of the space looks like: the logo on this background.
SPACE_BACKGROUND = (29, 111, 143, 255)


def _logo(size: int) -> Image.Image:
    """The logo, ``size`` pixels wide: black on transparent."""
    return Image.open(LOGO_PNG).convert("RGBA").resize((size, size), Image.LANCZOS)


def room_avatar() -> Image.Image:
    """The avatar of the example chat: the logo on white - an avatar is
    not transparent, and the documentation has a dark theme too.
    """
    avatar = Image.new("RGBA", (SIZE, SIZE), (255, 255, 255, 255))
    avatar.alpha_composite(_logo(SIZE))
    return avatar


def space_avatar() -> Image.Image:
    """The avatar of the example space: the logo, smaller, on a colour -
    so it can be told from the avatar of the chat.
    """
    avatar = Image.new("RGBA", (SIZE, SIZE), SPACE_BACKGROUND)
    logo = _logo(SIZE * 3 // 4)
    offset = (SIZE - logo.width) // 2
    avatar.alpha_composite(logo, (offset, offset))
    return avatar


def _png(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()


def generate(output: Path = OUTPUT) -> list[Path]:
    """Write the four images into ``output`` and return their paths."""
    output.mkdir(parents=True, exist_ok=True)
    images = {
        "room-before": _png(room_avatar()),
        "space-before": _png(space_avatar()),
    }
    images["room-after"] = RoomSpeaker().merge(images["room-before"])
    images["space-after"] = SpaceSpeaker().merge(images["space-before"])
    paths = []
    for name, data in images.items():
        path = output / f"{name}.png"
        path.write_bytes(data)
        paths.append(path)
    return paths


if __name__ == "__main__":
    for written in generate():
        print(written)
