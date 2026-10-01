"""Merging icons into images."""

import io

from PIL import Image

from matrix_jitsi_bot.icon.merge import (
    DEFAULT_SIZE,
    IconMerge,
    SpeakerFull,
    SpeakerTopRight,
)

_RED = (255, 0, 0, 255)


class _SvgBottomLeft(IconMerge):
    icon_file = "speaker.svg"
    corner = "bottom-left"
    scale = 0.5


def _png(size=(100, 60), mode="RGBA", fmt="PNG") -> bytes:
    out = io.BytesIO()
    Image.new(mode, size, "red").save(out, format=fmt)
    return out.getvalue()


def _open(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


def test_default_is_the_top_right_cut_speaker() -> None:
    merger = SpeakerTopRight()
    assert merger.icon_path.name == "speaker-top-right-cut.png"
    assert merger.icon_path.is_file()
    assert (merger.corner, merger.scale) == ("top-right", 0.4)


def test_icon_covers_40_percent_of_the_shorter_side_in_the_corner() -> None:
    result = _open(SpeakerTopRight().merge(_png()))
    assert result.size == (100, 60)
    # 40% of 60 = 24 pixels: x 76..99, y 0..23

    assert result.getpixel((88, 12)) != _RED
    assert result.getpixel((1, 1)) == _RED
    assert result.getpixel((70, 12)) == _RED
    assert result.getpixel((88, 40)) == _RED
    assert result.getpixel((1, 58)) == _RED


def test_other_icons_and_corners_by_subclassing() -> None:
    result = _open(_SvgBottomLeft().merge(_png()))
    assert result.getpixel((15, 45)) != _RED
    assert result.getpixel((99, 0)) == _RED


def test_without_an_image_the_icon_is_on_a_blank_square() -> None:
    result = _open(SpeakerTopRight().merge(None))
    assert result.size == (DEFAULT_SIZE, DEFAULT_SIZE)
    assert result.getpixel((1, DEFAULT_SIZE - 2)) == (0, 0, 0, 0)
    assert result.getpixel((DEFAULT_SIZE - 40, 40))[3] > 0


def test_other_input_formats_give_png() -> None:
    result = _open(SpeakerTopRight().merge(_png((50, 50), "RGB", "JPEG")))
    assert result.format == "PNG"


def test_transparent_icon_pixels_keep_the_image_below() -> None:
    """The icon is cut off at its top right: there it is transparent,
    so the image shows through unchanged."""
    result = _open(SpeakerTopRight().merge(_png()))
    assert result.getpixel((99, 0)) == _RED


def test_transparent_image_pixels_stay_transparent_around_the_icon() -> None:
    """Nothing is filled in behind the icon's own transparent pixels."""
    result = _open(SpeakerTopRight().merge(None))
    assert result.getpixel((DEFAULT_SIZE - 1, 0))[3] == 0


def test_partly_transparent_icon_pixels_are_blended() -> None:
    icon = _open(SpeakerTopRight().merge(_png((100, 100))))
    plain = Image.open(SpeakerTopRight().icon_path).convert("RGBA")
    edge = next(
        (x, y)
        for x in range(plain.width)
        for y in range(plain.height)
        if 0 < plain.getpixel((x, y))[3] < 255
    )
    # The blended pixel is neither the pure image colour nor the icon's.
    x, y = 60 + edge[0] * 40 // plain.width, edge[1] * 40 // plain.height
    assert icon.getpixel((x, y)) != _RED


def test_write_a_merged_example_next_to_the_icons() -> None:
    """Leaves ``merged-example.png`` in the icon directory to look at."""
    from matrix_jitsi_bot.icon.merge import ICON_DIRECTORY

    base = Image.new("RGBA", (400, 300), (30, 120, 200, 255))
    source = io.BytesIO()
    base.save(source, format="PNG")
    target = ICON_DIRECTORY / "merged-example.png"
    target.write_bytes(SpeakerTopRight().merge(source.getvalue()))
    assert _open(target.read_bytes()).size == (400, 300)


def test_full_speaker_fills_the_image() -> None:
    result = _open(SpeakerFull().merge(None))
    assert result.size == (DEFAULT_SIZE, DEFAULT_SIZE)
    assert result.getpixel((DEFAULT_SIZE // 2, DEFAULT_SIZE // 2))[3] == 255
    assert result.getpixel((0, 0))[3] == 0  # outside the round icon
