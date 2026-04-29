"""Redis pub/sub broadcaster for cross-process WebSocket delivery.

Unlike :class:`MemoryBroadcaster` (which only fans out within a
single process), this driver uses Redis pub/sub so every application
instance subscribed to the same Redis receives the message. Install
via ``pylar[broadcast-redis]`` (shares ``redis>=5.0``).

Usage::

    from redis.asyncio import Redis
    from pylar.broadcasting.drivers.redis import RedisBroadcaster

    broadcaster = RedisBroadcaster(Redis.from_url("redis://localhost"))
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

try:
    from redis.asyncio import Redis
    from redis.asyncio.client import PubSub
except ImportError:  # pragma: no cover
    raise ImportError(
        "RedisBroadcaster requires the 'redis' package. "
        "Install with: pip install 'pylar[broadcast-redis]'"
    ) from None


class RedisBroadcaster:
    """Cross-process broadcaster backed by Redis pub/sub.

    ``publish`` serialises the message to JSON and pushes it through
    Redis ``PUBLISH``. ``subscribe`` opens a Redis ``SUBSCRIBE`` and
    yields messages as they arrive.

    A single :class:`PubSub` connection is shared across all
    subscriptions to avoid leaking one connection per channel. The
    ``PubSub`` is created lazily on the first ``subscribe`` call and
    cleaned up on :meth:`close`.
    """

    def __init__(
        self,
        client: Redis,
        *,
        prefix: str = "pylar:broadcast:",
    ) -> None:
        self._client = client
        self._prefix = prefix
        self._pubsub: PubSub | None = None
        self._active_channels: set[str] = set()

    async def _get_pubsub(self) -> PubSub:
        if self._pubsub is None:
            self._pubsub = self._client.pubsub()
        return self._pubsub

    async def publish(self, channel: str, message: dict[str, Any]) -> None:
        redis_channel = f"{self._prefix}{channel}"
        await self._client.publish(redis_channel, json.dumps(message))

    async def subscribe(self, channel: str) -> AsyncIterator[dict[str, Any]]:
        redis_channel = f"{self._prefix}{channel}"
        pubsub = await self._get_pubsub()
        await pubsub.subscribe(redis_channel)
        self._active_channels.add(redis_channel)
        try:
            while True:
                msg = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if msg is not None and msg["type"] == "message":
                    # Only yield messages for this specific channel.
                    if msg.get("channel") in (redis_channel, redis_channel.encode()):
                        try:
                            data = json.loads(msg["data"])
                            if isinstance(data, dict):
                                yield data
                        except (json.JSONDecodeError, TypeError):
                            pass
                else:
                    await asyncio.sleep(0.01)
        finally:
            await pubsub.unsubscribe(redis_channel)
            self._active_channels.discard(redis_channel)

    async def close(self) -> None:
        """Unsubscribe all channels and close the shared PubSub."""
        if self._pubsub is not None:
            for ch in list(self._active_channels):
                await self._pubsub.unsubscribe(ch)
            self._active_channels.clear()
            await self._pubsub.close()
            self._pubsub = None

    def subscriber_count(self, channel: str) -> int:
        """Not available for Redis — pub/sub doesn't track subscribers."""
        return -1

    def channels(self) -> tuple[str, ...]:
        """Return the currently subscribed Redis channels."""
        return tuple(self._active_channels)
