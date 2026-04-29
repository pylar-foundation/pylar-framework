"""Behavioural tests for the cache layer."""

from __future__ import annotations

import time

import pytest

from pylar.cache import Cache, CacheStore, MemoryCacheStore


@pytest.fixture
def store() -> MemoryCacheStore:
    return MemoryCacheStore()


@pytest.fixture
def cache(store: MemoryCacheStore) -> Cache:
    return Cache(store)


# ----------------------------------------------------------------- store


async def test_put_and_get_round_trip(store: MemoryCacheStore) -> None:
    await store.put("user:1", {"id": 1, "name": "alice"})
    assert await store.get("user:1") == {"id": 1, "name": "alice"}


async def test_get_missing_returns_none(store: MemoryCacheStore) -> None:
    assert await store.get("nope") is None


async def test_forget_removes_entry(store: MemoryCacheStore) -> None:
    await store.put("k", "v")
    await store.forget("k")
    assert await store.get("k") is None


async def test_flush_removes_everything(store: MemoryCacheStore) -> None:
    await store.put("a", 1)
    await store.put("b", 2)
    await store.flush()
    assert store.size() == 0


async def test_ttl_expires_entry(store: MemoryCacheStore, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_time = [1000.0]

    def fake_monotonic() -> float:
        return fake_time[0]

    monkeypatch.setattr(time, "monotonic", fake_monotonic)

    await store.put("k", "v", ttl=60)
    assert await store.get("k") == "v"

    fake_time[0] = 1059.9
    assert await store.get("k") == "v"

    fake_time[0] = 1060.1
    assert await store.get("k") is None


async def test_protocol_is_runtime_checkable(store: MemoryCacheStore) -> None:
    assert isinstance(store, CacheStore)


# ------------------------------------------------------------------ facade


async def test_cache_has_returns_bool(cache: Cache) -> None:
    assert await cache.has("k") is False
    await cache.put("k", 1)
    assert await cache.has("k") is True


async def test_remember_caches_factory_result(cache: Cache) -> None:
    calls = {"n": 0}

    async def factory() -> int:
        calls["n"] += 1
        return 42

    first = await cache.remember("answer", ttl=None, factory=factory)
    second = await cache.remember("answer", ttl=None, factory=factory)

    assert first == 42
    assert second == 42
    assert calls["n"] == 1  # second call hit the cache


async def test_remember_recomputes_after_forget(cache: Cache) -> None:
    calls = {"n": 0}

    async def factory() -> int:
        calls["n"] += 1
        return calls["n"]

    assert await cache.remember("k", ttl=None, factory=factory) == 1
    await cache.forget("k")
    assert await cache.remember("k", ttl=None, factory=factory) == 2


async def test_remember_with_lock_computes_once(cache: Cache) -> None:
    """Factory runs exactly once even under concurrent misses."""
    import asyncio as _asyncio

    calls = {"n": 0}

    async def factory() -> int:
        calls["n"] += 1
        await _asyncio.sleep(0.05)  # simulate slow compute
        return 123

    # Fire three concurrent misses — only one should compute.
    results = await _asyncio.gather(
        cache.remember_with_lock("k", ttl=None, factory=factory),
        cache.remember_with_lock("k", ttl=None, factory=factory),
        cache.remember_with_lock("k", ttl=None, factory=factory),
    )
    assert results == [123, 123, 123]
    assert calls["n"] == 1


async def test_remember_with_lock_recomputes_after_forget(cache: Cache) -> None:
    calls = {"n": 0}

    async def factory() -> int:
        calls["n"] += 1
        return calls["n"]

    assert await cache.remember_with_lock("k", ttl=None, factory=factory) == 1
    await cache.forget("k")
    assert await cache.remember_with_lock("k", ttl=None, factory=factory) == 2
