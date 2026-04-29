"""The :class:`Broadcaster` Protocol — server-to-client message fan-out."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Broadcaster(Protocol):
    """A server-side fan-out for typed messages.

    Two operations: :meth:`publish` pushes a message onto a named
    channel, :meth:`subscribe` returns an async iterator that yields
    every message subsequently published on that channel until the
    consumer breaks out of the loop. Driver implementations are free
    to back this with in-memory queues, Redis pub/sub, or any other
    transport — the contract every consumer depends on is the four
    lines below.
    """

    async def publish(self, channel: str, message: dict[str, Any]) -> None: ...

    def subscribe(self, channel: str) -> AsyncIterator[dict[str, Any]]: ...
