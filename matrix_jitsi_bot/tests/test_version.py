"""Telling a release from a development version."""

import importlib

import pytest

#: Not ``from matrix_jitsi_bot import version``: the package exports the
#: version string under that name, hiding the module.
version = importlib.import_module("matrix_jitsi_bot.version")

pytestmark = pytest.mark.no_database


@pytest.mark.parametrize(
    ("number", "development"),
    [
        ("0.1.0", False),
        ("1.2.3", False),
        ("0.1.1.dev7", True),
        ("0.1.dev14", True),
        ("0.0.0dev0", True),  # when there is no version at all
    ],
)
def test_a_development_version_is_told_by_dev(monkeypatch, number, development) -> None:
    monkeypatch.setattr(version, "__version__", number)
    assert version.is_development() is development


def test_is_development_is_exported() -> None:
    assert "is_development" in version.__all__
