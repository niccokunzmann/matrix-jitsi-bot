"""The logo and the icons are files of the package - so they are installed
with it, and are in the Docker image, which holds the package directory.
"""

import io

import pytest
from PIL import Image

from matrix_jitsi_bot.icon import ICON_DIRECTORY, LOGO_PNG, LOGO_SVG
from matrix_jitsi_bot.icon.merge import RoomSpeaker, SpaceSpeaker, SpeakerFull

pytestmark = pytest.mark.no_database


def test_the_logo_is_in_the_package_directory() -> None:
    import matrix_jitsi_bot

    package = ICON_DIRECTORY.parent
    assert package.name == "matrix_jitsi_bot"
    assert package == __import__("pathlib").Path(matrix_jitsi_bot.__file__).parent
    assert LOGO_SVG.parent == LOGO_PNG.parent == ICON_DIRECTORY


def test_the_logo_is_a_valid_png() -> None:
    image = Image.open(LOGO_PNG)
    assert image.format == "PNG"
    assert image.width == image.height  # a logo is square


def test_the_logo_is_a_valid_svg() -> None:
    import cairosvg

    png = cairosvg.svg2png(url=str(LOGO_SVG), output_width=32)
    assert Image.open(io.BytesIO(png)).width == 32


@pytest.mark.parametrize("merger", [RoomSpeaker(), SpaceSpeaker(), SpeakerFull()])
def test_the_icons_of_the_speakers_are_in_the_package_directory(merger) -> None:
    assert merger.icon_path.parent == ICON_DIRECTORY
    assert merger.icon_path.is_file()
