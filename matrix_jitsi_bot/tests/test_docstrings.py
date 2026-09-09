"""Documentation hygiene: every module, class and function is documented,
and every docstring's backtick markup is well-formed.

The rule (see `AskUserQuestion`-free instruction, taken at face value):
a docstring may reference another function/class/attribute only via an
explicit, role-qualified cross-reference - e.g. ``:py:meth:`fully.
qualified.name``` - never a bare ```` `name` ```` (ambiguous: Sphinx's
default "any" role resolves it by short name alone, which silently
picks the wrong target if that name isn't unique project-wide).
Anything that isn't a real Python object - a filename, a config key, a
literal string - uses double backticks (``` `` ```), RST's actual
"literal code" markup, instead.

A role-qualified reference's opening backtick is always immediately
preceded by ``:`` (the end of the role name, e.g. ``:py:meth:```); its
closing backtick never is. So in a docstring using only role-qualified
single-backtick references (never a bare one), the count of ``:```
substrings equals the count of single backticks *not* preceded by
``:`` - that's what `test_docstring_backticks_are_role_qualified`
checks, per-docstring, ignoring ```` `` ```` code spans entirely.

The `docstring` fixture is parametrized one docstring per test case
(rather than a single list), so a failure names the exact
module/class/function it's about in the test ID, instead of one
aggregate test listing every offender.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_SKIP_DIRS = {"tests", "migrations"}
_SKIP_FILES = {"_version.py"}


@dataclass
class Docstring:
    """A module/class/function docstring, with its location and kind."""

    location: str
    kind: str
    docstring: str | None

    def __str__(self) -> str:
        return self.location


def _walk(node: ast.AST, prefix: str):
    """Yield a `Docstring` for `node` and everything nested in it -
    `kind` is ``"module"``, ``"class"`` or ``"function"``.
    """
    if isinstance(node, ast.Module):
        yield Docstring(prefix or "<module>", "module", ast.get_docstring(node))
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            qualname = f"{prefix}.{child.name}" if prefix else child.name
            kind = "class" if isinstance(child, ast.ClassDef) else "function"
            yield Docstring(qualname, kind, ast.get_docstring(child))
            yield from _walk(child, qualname)


def _iter_docstrings():
    for path in sorted(_ROOT.rglob("*.py")):
        rel = path.relative_to(_ROOT)
        if any(part in _SKIP_DIRS for part in rel.parts) or path.name in _SKIP_FILES:
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for entry in _walk(tree, ""):
            entry.location = f"{rel}::{entry.location}"
            yield entry


@pytest.fixture(params=list(_iter_docstrings()), ids=str)
def docstring(request) -> Docstring:
    """One module/class/function docstring from `matrix_jitsi_bot`,
    excluding tests, migrations and the generated `_version.py` - see
    the module docstring for why this is parametrized rather than a
    single list.
    """
    return request.param


def test_every_function_has_a_docstring(docstring: Docstring) -> None:
    if docstring.kind != "function":
        pytest.skip("not a function")
    assert docstring.docstring, f"{docstring.location} has no docstring"


def _backtick_balance(text: str) -> tuple[int, int]:
    """Count role-qualified (``:```-prefixed) vs bare single backticks
    in `text`, ignoring ```` `` ```` (double-backtick, RST literal)
    spans entirely - see the module docstring for why these should be
    equal in a well-formed docstring.
    """
    prefixed = bare = 0
    i = 0
    while i < len(text):
        if text[i] == "`":
            if text[i : i + 2] == "``":
                i += 2
                continue
            if i > 0 and text[i - 1] == ":":
                prefixed += 1
            else:
                bare += 1
            i += 1
        else:
            i += 1
    return prefixed, bare


def test_docstring_backticks_are_role_qualified(docstring: Docstring) -> None:
    if not docstring.docstring:
        pytest.skip("no docstring")
    prefixed, bare = _backtick_balance(docstring.docstring)
    assert prefixed == bare, (
        f"{docstring.location}: {prefixed} role-qualified vs {bare} bare backtick(s) "
        "- every single-backtick reference must be role-qualified "
        "(e.g. :py:meth:`...`), never bare"
    )


def test_docstring_backtick_count_is_even(docstring: Docstring) -> None:
    """Every backtick (single or double) opens or closes some RST
    markup span, so - independent of role-qualification - the total
    count of ``` ` ``` characters in a well-formed docstring is even; an
    odd count means a span was left unclosed (or a stray backtick).
    """
    if not docstring.docstring:
        pytest.skip("no docstring")
    count = docstring.docstring.count("`")
    assert count % 2 == 0, f"{docstring.location}: {count} backtick(s)"
