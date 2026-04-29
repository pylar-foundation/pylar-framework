"""Behavioural tests for :class:`MemoryBroadcaster`."""

from __future__ import annotations

import asyncio

import pytest

from pylar.broadcasting import Broadcaster, MemoryBroadcaster


@pytest.fixture
def broadcaster() -> MemoryBroadcaster:
    return MemoryBroadcaster()


async def test_publish_with_no_subscribers_is_noop(
    broadcaster: MemoryBroadcaster,
) -> None:
    await broadcaster.publish("empty", {"x": 1})  # does not raise


async def test_subscriber_receives_published_message(
    broadcaster: MemoryBroadcaster,
) -> None:
    received: list[dict[str, object]] = []

    async def consume() -> None:
        gen = broadcaster.subscribe("chat")
        try:
            async for message in gen:
                received.append(message)
                if len(received) == 2:
                    break
        finally:
            await gen.aclose()

    consumer_task = asyncio.create_task(consume())
    await asyncio.sleep(0)  # let consumer install itself
    await broadcaster.publish("chat", {"text": "hello"})
    await broadcaster.publish("chat", {"text": "world"})
    await consumer_task

    assert received == [{"text": "hello"}, {"text": "world"}]


async def test_subscriber_isolated_per_channel(
    broadcaster: MemoryBroadcaster,
) -> None:
    received: list[dict[str, object]] = []

    async def consume() -> None:
        gen = broadcaster.subscribe("a")
        try:
            async for message in gen:
                received.append(message)
                break
        finally:
            await gen.aclose()

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    await broadcaster.publish("b", {"text": "ignored"})
    await broadcaster.publish("a", {"text": "delivered"})
    await task

    assert received == [{"text": "delivered"}]


async def test_subscriber_count_tracks_lifecycle(
    broadcaster: MemoryBroadcaster,
) -> None:
    received: list[dict[str, object]] = []

    async def consume() -> None:
        # Explicit aclose() ensures the subscribe() async generator's
        # finally block runs deterministically, removing the queue from
        # the broadcaster's subscriber list before the test asserts on
        # the count.
        gen = broadcaster.subscribe("ping")
        try:
            async for message in gen:
                received.append(message)
                break
        finally:
            await gen.aclose()

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    assert broadcaster.subscriber_count("ping") == 1

    await broadcaster.publish("ping", {})
    await task
    assert broadcaster.subscriber_count("ping") == 0


def test_memory_broadcaster_satisfies_protocol(
    broadcaster: MemoryBroadcaster,
) -> None:
    assert isinstance(broadcaster, Broadcaster)


# ---- Redis PubSub connection pooling ----


async def test_redis_broadcaster_reuses_single_pubsub() -> None:
    """Second subscribe() should reuse the first PubSub, not create a new one."""
    import pytest
    pytest.importorskip("fakeredis")
    from fakeredis.aioredis import FakeRedis

    from pylar.broadcasting.drivers.redis import RedisBroadcaster

    client = FakeRedis()
    try:
        b = RedisBroadcaster(client, prefix="test:")
        assert b._pubsub is None
        pubsub1 = await b._get_pubsub()
        pubsub2 = await b._get_pubsub()
        assert pubsub1 is pubsub2
    finally:
        await client.aclose()


async def test_redis_broadcaster_close_cleans_up() -> None:
    """close() clears active channels and resets the pubsub handle."""
    import pytest
    pytest.importorskip("fakeredis")
    from fakeredis.aioredis import FakeRedis

    from pylar.broadcasting.drivers.redis import RedisBroadcaster

    client = FakeRedis()
    try:
        b = RedisBroadcaster(client, prefix="test:")
        pubsub = await b._get_pubsub()
        await pubsub.subscribe("test:ch")
        b._active_channels.add("test:ch")
        await b.close()
        assert b._pubsub is None
        assert b._active_channels == set()
    finally:
        await client.aclose()
