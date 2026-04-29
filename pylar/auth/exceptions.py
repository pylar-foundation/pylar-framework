"""Exceptions raised by the auth layer."""

from __future__ import annotations


class AuthError(Exception):
    """Base class for authentication / authorization errors."""


class AuthenticationError(AuthError):
    """Raised when a request cannot be associated with a valid user."""


class AuthorizationError(AuthError):
    """Raised when an authenticated user is not allowed to perform an action.

    The route compiler turns this into a ``403 Forbidden`` JSON response so
    that controllers can simply ``await gate.authorize(...)`` and trust the
    framework to render the rejection.
    """

    def __init__(self, ability: str, *, detail: str | None = None) -> None:
        self.ability = ability
        self.detail = detail or f"Not authorized to perform {ability!r}"
        super().__init__(self.detail)


class NoCurrentUserError(AuthError):
    """Raised when ``current_user()`` is called outside an authenticated scope."""
