"""Tests for the Redis-backed cache store."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from pylar.cache import Cache
from pylar.cache.drivers.redis import RedisCacheStore

pytest.importorskip("fakeredis")
from fakeredis.aioredis import FakeRedis


@pytest.fixture
async def store() -> AsyncIterator[RedisCacheStore]:
    client = FakeRedis()
    yield RedisCacheStore(client, prefix="test:cache:")
    await client.aclose()


# -------------------------------------------------------- Protocol basics


async def test_round_trip(store: RedisCacheStore) -> None:
    await store.put("k", {"hello": "world"})
    assert await store.get("k") == {"hello": "world"}


async def test_get_missing(store: RedisCacheStore) -> None:
    assert await store.get("nope") is None


async def test_forget(store: RedisCacheStore) -> None:
    await store.put("k", 1)
    await store.forget("k")
    assert await store.get("k") is None


async def test_flush(store: RedisCacheStore) -> None:
    await store.put("a", 1)
    await store.put("b", 2)
    await store.flush()
    assert await store.get("a") is None
    assert await store.get("b") is None


async def test_ttl_expires(store: RedisCacheStore) -> None:
    await store.put("k", "v", ttl=1)
    await asyncio.sleep(1.1)
    assert await store.get("k") is None


async def test_stores_python_objects(store: RedisCacheStore) -> None:
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    await store.put("dt", now)
    assert await store.get("dt") == now


# -------------------------------------------------------- Native atomics


async def test_add_setnx(store: RedisCacheStore) -> None:
    assert await store.add("k", "first") is True
    assert await store.add("k", "second") is False
    assert await store.get("k") == "first"


async def test_increment_from_zero(store: RedisCacheStore) -> None:
    assert await store.increment("counter") == 1
    assert await store.increment("counter") == 2
    assert await store.increment("counter", by=5) == 7


async def test_decrement(store: RedisCacheStore) -> None:
    await store.increment("counter", by=10)
    assert await store.decrement("counter", by=3) == 7


# ------------------------------------------------ Facade delegation


async def test_facade_delegates_add_to_native(store: RedisCacheStore) -> None:
    cache = Cache(store)
    assert await cache.add("x", "first") is True
    assert await cache.add("x", "second") is False


async def test_facade_delegates_increment_to_native(store: RedisCacheStore) -> None:
    cache = Cache(store)
    assert await cache.increment("c") == 1
    assert await cache.increment("c", by=4) == 5
    assert await cache.decrement("c") == 4


# ---------------------------------------- Maintenance mode via cache


async def test_maintenance_via_cache(store: RedisCacheStore) -> None:
    cache = Cache(store)
    from pylar.http.middlewares.maintenance import MaintenanceModeMiddleware

    class CacheMaintenance(MaintenanceModeMiddleware):
        backend = "cache"

    mw = CacheMaintenance(cache=cache)

    # Not down yet.
    assert await mw._is_down() is False

    # Set flag via cache.
    await cache.put("pylar:maintenance:down", "1")
    assert await mw._is_down() is True

    # Clear flag.
    await cache.forget("pylar:maintenance:down")
    assert await mw._is_down() is False
