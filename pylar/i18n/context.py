"""Ambient locale via a context variable.

Mirrors :mod:`pylar.database.session` and :mod:`pylar.auth.context`: a
middleware (or test helper) opens a scope with :func:`with_locale`, and
the :class:`Translator` reads the active locale through
:func:`current_locale` instead of receiving it as a parameter on every
call.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_current_locale: ContextVar[str | None] = ContextVar(
    "pylar_current_locale", default=None
)


def current_locale() -> str | None:
    """Return the active locale, or ``None`` if no scope is open."""
    return _current_locale.get()


@contextmanager
def with_locale(locale: str | None) -> Iterator[None]:
    """Install *locale* as the current one for the duration of the block."""
    token = _current_locale.set(locale)
    try:
        yield
    finally:
        _current_locale.reset(token)
