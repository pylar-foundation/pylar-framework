"""Helpers for converting between PascalCase, snake_case, and kebab-case."""

from __future__ import annotations

import re

from pylar.console.make.exceptions import InvalidNameError

_PASCAL_RE = re.compile(r"^[A-Z][A-Za-z0-9]*$")


def validate_pascal(name: str) -> str:
    """Return *name* if it looks like a PascalCase identifier, else raise."""
    if not _PASCAL_RE.match(name):
        raise InvalidNameError(
            f"{name!r} is not a valid PascalCase identifier — "
            "must start with a capital letter and contain only letters and digits"
        )
    return name


def to_snake(name: str) -> str:
    """Convert ``PascalCase``/``camelCase`` to ``snake_case``.

    Sequences of capitals are kept together (``HTTPClient`` → ``http_client``)
    so common acronyms render the way humans expect.
    """
    # Insert an underscore before each uppercase letter that follows a
    # lowercase one, then before each uppercase letter that is followed by
    # a lowercase one. The two passes together handle both ``UserName`` and
    # ``HTTPRequest``.
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    s2 = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1)
    return s2.lower()


def to_kebab(name: str) -> str:
    """Convert ``PascalCase`` to ``kebab-case``."""
    return to_snake(name).replace("_", "-")
