"""Ambient access to the authenticated user via a context variable.

Mirrors :mod:`pylar.database.session`: an HTTP middleware (or test helper)
opens a scope, and downstream code calls :func:`current_user` to read the
authenticated identity. There is no global default — code outside an
authenticated scope gets a clear :class:`NoCurrentUserError`.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from pylar.auth.contracts import Authenticatable
from pylar.auth.exceptions import NoCurrentUserError

_current_user: ContextVar[Authenticatable | None] = ContextVar(
    "pylar_current_user", default=None
)


def current_user() -> Authenticatable:
    """Return the active user for this task, or raise :class:`NoCurrentUserError`."""
    user = _current_user.get()
    if user is None:
        raise NoCurrentUserError(
            "No authenticated user in scope. Either install AuthMiddleware on "
            "this route or wrap your code in `with authenticate_as(user):`."
        )
    return user


def current_user_or_none() -> Authenticatable | None:
    """Return the active user, or ``None`` if the request is unauthenticated."""
    return _current_user.get()


@contextmanager
def authenticate_as(user: Authenticatable | None) -> Iterator[None]:
    """Install *user* as the current identity for the duration of the block.

    Used by :class:`AuthMiddleware` to bind the resolved user to the request
    task, and by tests that want to exercise authorization without going
    through the HTTP layer. Passing ``None`` represents an anonymous scope —
    :func:`current_user_or_none` returns ``None`` inside it.
    """
    token = _current_user.set(user)
    try:
        yield
    finally:
        _current_user.reset(token)
