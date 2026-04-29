"""The :class:`SessionStore` Protocol every backend implements."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SessionStore(Protocol):
    """A minimal session-payload backend.

    Pylar deliberately keeps the contract narrow — three methods —
    so swapping memory for file, database, or Redis is one container
    rebinding. The store deals in opaque dictionaries keyed by an
    arbitrary string id; the middleware is responsible for picking
    the id (UUID), signing it for the cookie, and rotating it on
    :meth:`Session.regenerate`.
    """

    async def read(self, session_id: str) -> dict[str, Any] | None: ...

    async def write(
        self,
        session_id: str,
        data: dict[str, Any],
        *,
        ttl_seconds: int,
    ) -> None: ...

    async def destroy(self, session_id: str) -> None: ...
