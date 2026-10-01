"""The icons the bot draws on avatars, the logo, and how to merge them in.

The files (SVG or PNG) live in this directory - so they are part of the
installed package and of the Docker image - see
:py:mod:`matrix_jitsi_bot.icon.merge` for drawing them into an image.
"""

from pathlib import Path

#: Where the logo and the icons are.
ICON_DIRECTORY = Path(__file__).parent

#: The logo of matrix-jitsi-bot, as a vector graphic - also the favicon of
#: the documentation.
LOGO_SVG = ICON_DIRECTORY / "logo.svg"

#: The logo of matrix-jitsi-bot, as an image.
LOGO_PNG = ICON_DIRECTORY / "logo.png"
