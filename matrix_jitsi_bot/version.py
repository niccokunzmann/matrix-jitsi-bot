"""Version information on icalendar.

This module provides a stable interface to the generated :file:`_version.py` file.

"""

try:
    from ._version import __version__, __version_tuple__, version, version_tuple
except ModuleNotFoundError:
    __version__ = version = "0.0.0dev0"
    __version_tuple__ = version_tuple = (0, 0, 0, "dev0")


def is_development() -> bool:
    """Whether this is a development version rather than a release.

    Between two releases the version carries ``dev`` - ``0.1.1.dev7``,
    seven commits after ``0.1.0`` - and so does the version when there
    is none (``0.0.0dev0``). A release, built from a tag, does not:
    ``0.1.0``.
    """
    return "dev" in __version__


def documentation_url(page: str) -> str:
    """The address of ``page`` - e.g. ``"using-a-bot/track-a-conference"`` -
    in the documentation of this version of the bot: ``stable`` for a
    release, ``latest`` for a development version, see
    :py:func:`~matrix_jitsi_bot.version.is_development`.
    """
    kind = "latest" if is_development() else "stable"
    return f"https://matrix-jitsi-bot.readthedocs.io/en/{kind}/{page}.html"


__all__ = [
    "__version__",
    "__version_tuple__",
    "documentation_url",
    "is_development",
    "version",
    "version_tuple",
]
