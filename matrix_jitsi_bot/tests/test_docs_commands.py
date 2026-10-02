"""The commands page documents every command, and each in the same way."""

import re
from pathlib import Path

import pytest

PAGE = Path(__file__).resolve().parents[2] / "docs" / "using-a-bot" / "commands.rst"

pytestmark = pytest.mark.no_database

#: What a command is set up with: these have something to undo.
_CONFIGURATION = (
    "track ",
    "change avatar",
    "create conference status message",
    "pause",
    "unpause",
    "leave",
    "don't track",
)


def _sections() -> dict[str, str]:
    """The text of every section with a label ``command-...``, by label -
    a command group, or a variant of one.
    """
    text = PAGE.read_text()
    parts = re.split(r"^\.\. _(command-[a-z-]+):$", text, flags=re.MULTILINE)
    return dict(zip(parts[1::2], parts[2::2], strict=True))


def _command(section: str) -> str | None:
    """The first command shown in ``section``, after ``@jitsi-bot``."""
    match = re.search(r"^    @jitsi-bot (.+)$", section, flags=re.MULTILINE)
    return match.group(1) if match else None


def test_every_command_of_the_bot_is_documented() -> None:
    from matrix_jitsi_bot.interactions import AllInteractions

    text = PAGE.read_text()
    handlers = {
        reaction.func.__name__
        for reaction in AllInteractions().reactions
        # What it does while a chat is paused is explained with unpausing.
        if reaction.func.__name__ != "react_while_paused"
    }

    assert [name for name in sorted(handlers) if name not in text] == []


def test_every_section_with_a_command_has_an_explanation() -> None:
    sections = {k: v for k, v in _sections().items() if _command(v)}
    assert len(sections) >= 15
    missing = [k for k, v in sections.items() if ".. dropdown:: Explanation" not in v]
    assert missing == []


def test_every_command_that_sets_something_up_says_how_to_undo_it() -> None:
    sections = {
        k: v
        for k, v in _sections().items()
        if (command := _command(v)) and command.startswith(_CONFIGURATION)
    }
    assert "command-track-start-and-end" in sections
    assert "command-leave" in sections
    missing = [
        k
        for k, v in sections.items()
        if ".. dropdown:: Undo this configuration" not in v
    ]
    assert missing == []


def test_the_dropdowns_come_in_one_order() -> None:
    order = ["Explanation", "Other ways to say it", "Undo this configuration"]
    for label, section in _sections().items():
        found = [
            title
            for title in re.findall(
                r"^\.\. dropdown:: (.+)$", section, flags=re.MULTILINE
            )
            if title in order
        ]
        assert found == sorted(found, key=order.index), label


def test_what_applies_to_every_command_is_referenced_not_repeated() -> None:
    """An undo part shows the commands specific to it: ``do not`` and the
    moderators are said once, and so is "stop everything"."""
    undo = ".. dropdown:: Undo this configuration"
    for label, section in _sections().items():
        if undo not in section:
            continue
        part = section[section.index(undo) :]
        assert "do not" not in part.split(".. include::")[0], label
    track = _sections()["command-track-start-and-end"]
    part = track[track.index(undo) :]
    assert "don't track https://" not in re.sub(
        r"don't track (?:open |close )?status of https://", "", part
    )
