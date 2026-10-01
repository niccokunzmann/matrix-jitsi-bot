"""Merging an icon into a room's avatar or any PNG file.

:py:class:`~matrix_jitsi_bot.icon.merge.IconMerge` draws an icon file
(SVG or PNG) into a corner or the side of an image, scaled to a fraction of the
image, and returns the result as PNG. Its subclasses set which icon,
where and how big - see
:py:class:`~matrix_jitsi_bot.icon.merge.SpeakerTopRight`, the default.
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING, ClassVar, Literal

from . import ICON_DIRECTORY

if TYPE_CHECKING:
    from pathlib import Path

    from PIL import Image


#: The side length in pixels of the image made for a room without an avatar.
DEFAULT_SIZE = 256

Position = Literal[
    "top-left",
    "top-right",
    "bottom-left",
    "bottom-right",
    "center-left",
    "center-right",
]


class IconMerge:
    """Draws :py:attr:`~matrix_jitsi_bot.icon.merge.IconMerge.icon_file`
    into :py:attr:`~matrix_jitsi_bot.icon.merge.IconMerge.position` in an
    image. The icon is scaled to
    :py:attr:`~matrix_jitsi_bot.icon.merge.IconMerge.scale` of the
    image's shorter side, keeping its proportions. Subclass it to
    choose another icon, position or size.
    """

    #: The icon's file name in :py:data:`~matrix_jitsi_bot.icon.ICON_DIRECTORY`.
    icon_file: ClassVar[str] = "speaker-full.png"
    #: Where the icon is drawn.
    position: ClassVar[Position] = "bottom-right"
    #: The icon's width as a fraction of min(width, height) of the image.
    scale: ClassVar[float] = 0.4

    @property
    def icon_path(self) -> Path:
        """Where the icon file is."""
        return ICON_DIRECTORY / self.icon_file

    def merge(self, image: bytes | None) -> bytes | None:
        """``image`` (any format Pillow reads; ``None``: a blank square,
        e.g. for a room without an avatar) with the icon drawn in, as PNG.
        """
        from PIL import Image

        if image:
            base = Image.open(io.BytesIO(image)).convert("RGBA")
        else:
            base = Image.new("RGBA", (DEFAULT_SIZE, DEFAULT_SIZE), (0, 0, 0, 0))
        icon = self._load_icon(max(1, round(min(base.size) * self.scale)))
        vertical, horizontal = self.position.split("-")
        x = 0 if horizontal == "left" else base.width - icon.width
        if vertical == "center":
            y = (base.height - icon.height) // 2
        else:
            y = 0 if vertical == "top" else base.height - icon.height
        base.alpha_composite(icon, (x, y))
        result = io.BytesIO()
        base.save(result, format="PNG")
        return result.getvalue()

    def _load_icon(self, width: int) -> Image.Image:
        """The icon as an RGBA image scaled to ``width`` pixels wide."""
        from PIL import Image

        path = self.icon_path
        if path.suffix.lower() == ".svg":
            import cairosvg

            png = cairosvg.svg2png(url=str(path), output_width=width)
            icon = Image.open(io.BytesIO(png))
        else:
            icon = Image.open(path)
        icon = icon.convert("RGBA")
        if icon.width != width:
            height = max(1, round(icon.height * width / icon.width))
            icon = icon.resize((width, height), Image.Resampling.LANCZOS)
        return icon


class SpeakerTopRight(IconMerge):
    """The default: the speaker, cut off at its top and right, in the
    top-right corner where the cut sides sit flush with the edges of the
    image, 40% of the image's shorter side wide. Shown while a
    conference is active.
    """

    icon_file = "speaker-top-right-cut.png"
    position = "top-right"
    scale = 0.4


class RoomSpeaker(IconMerge):
    """The whole speaker at the right, in the middle of the height, half
    as wide as the shorter side of the image: shown on the avatar of a
    chat while a conference is active.
    """

    icon_file = "speaker-full.png"
    position = "center-right"
    scale = 0.5


class SpaceSpeaker(IconMerge):
    """The whole speaker in the bottom-right corner, half as wide as the
    shorter side of the image: shown on the avatar of a space while a
    conference is active.
    """

    icon_file = "speaker-full.png"
    position = "bottom-right"
    scale = 0.5


class SpeakerFull(IconMerge):
    """The whole speaker icon, filling the image: the avatar of a room
    that has none of its own while a conference is active.
    """

    icon_file = "speaker-full.png"
    position = "top-right"
    scale = 1.0


class SamePicture(IconMerge):
    """Changes nothing: the same picture, only encoded as PNG - or no
    picture, if there is none. For tests of what happens around an avatar
    change that must not be seen in a real room.
    """

    def merge(self, image: bytes | None) -> bytes | None:
        """``image`` as PNG, without any icon."""
        from PIL import Image

        if not image:
            return None
        result = io.BytesIO()
        Image.open(io.BytesIO(image)).convert("RGBA").save(result, format="PNG")
        return result.getvalue()
