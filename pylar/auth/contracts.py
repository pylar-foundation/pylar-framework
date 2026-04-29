"""Protocols every auth-aware component talks to."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pylar.http.request import Request


@runtime_checkable
class Authenticatable(Protocol):
    """The minimum surface a user model must expose to participate in auth.

    The framework only needs an opaque identifier (used by guards to look up
    the user across requests) and the stored password hash (consumed by the
    :class:`PasswordHasher`). Anything beyond that — roles, permissions,
    profile fields — lives on the concrete user class and is reached through
    plain attribute access from policies and controllers.
    """

    @property
    def auth_identifier(self) -> object: ...

    @property
    def auth_password_hash(self) -> str: ...


class Guard(Protocol):
    """A pluggable strategy for resolving the current user from a request.

    Pylar does not ship with a built-in guard implementation: session,
    token, JWT, and Sanctum-style guards all have meaningfully different
    storage and security trade-offs and we want users to make those choices
    explicitly. The framework only fixes the contract — register your
    concrete guard in the container and :class:`AuthMiddleware` will use it.
    """

    async def authenticate(self, request: Request) -> Authenticatable | None: ...
