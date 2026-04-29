"""In-process broadcaster — useful for tests, dev, and single-process apps."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from pylar.broadcasting.exceptions import BroadcastingError


class MemoryBroadcaster:
    """An in-memory pub/sub fan-out backed by per-subscriber queues.

    Each call to :meth:`subscribe` allocates a fresh ``asyncio.Queue``
    and registers it under the requested channel. ``publish`` walks the
    subscriber list and pushes the message into every queue. The
    subscribe iterator cleans its own slot up in a ``finally`` block
    when the consumer breaks the loop, so disconnected clients do not
    leak queues.
    """

    #: Maximum messages buffered per subscriber before back-pressure.
    #: Prevents a slow consumer from causing unbounded memory growth.
    max_queue_size: int = 1000

    #: Maximum subscribers per channel. 0 means unlimited.
    max_subscribers_per_channel: int = 0

    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue[dict[str, Any]]]] = {}

    async def publish(self, channel: str, message: dict[str, Any]) -> None:
        for queue in list(self._subscribers.get(channel, [])):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                pass  # drop for slow consumers rather than blocking

    async def subscribe(self, channel: str) -> AsyncIterator[dict[str, Any]]:
        subs = self._subscribers.setdefault(channel, [])
        if 0 < self.max_subscribers_per_channel <= len(subs):
            raise BroadcastingError(
                f"Channel {channel!r} has reached the subscriber limit "
                f"({self.max_subscribers_per_channel})"
            )
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(
            maxsize=self.max_queue_size
        )
        self._subscribers.setdefault(channel, []).append(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            self._remove(channel, queue)

    # ----------------------------------------------------------- introspection

    def subscriber_count(self, channel: str) -> int:
        """How many active subscribers a channel currently has. Test affordance."""
        return len(self._subscribers.get(channel, []))

    def channels(self) -> tuple[str, ...]:
        return tuple(self._subscribers.keys())

    # ------------------------------------------------------------------ helpers

    def _remove(self, channel: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        if channel not in self._subscribers:
            return
        try:
            self._subscribers[channel].remove(queue)
        except ValueError:
            return
        if not self._subscribers[channel]:
            del self._subscribers[channel]
