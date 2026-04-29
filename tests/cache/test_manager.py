"""Tests for CacheManager — named cache stores."""

from __future__ import annotations

import pytest

from pylar.cache import Cache, CacheManager, MemoryCacheStore


def test_default_store_is_memory() -> None:
    manager = CacheManager()
    cache = manager.store()
    assert isinstance(cache, Cache)


def test_named_stores_are_independent() -> None:
    manager = CacheManager(
        default="hot",
        stores={
            "hot": {"driver": "memory"},
            "cold": {"driver": "memory"},
        },
    )
    hot = manager.store("hot")
    cold = manager.store("cold")
    assert hot is not cold


async def test_stores_are_cached() -> None:
    manager = CacheManager(
        stores={"main": {"driver": "memory"}},
        default="main",
    )
    first = manager.store("main")
    second = manager.store("main")
    assert first is second


async def test_default_store_shortcut() -> None:
    manager = CacheManager(
        default="primary",
        stores={"primary": {"driver": "memory"}},
    )
    assert manager.store() is manager.store("primary")


async def test_store_operations_work() -> None:
    manager = CacheManager(
        stores={"test": {"driver": "memory"}},
        default="test",
    )
    cache = manager.store()
    await cache.put("key", "value", ttl=60)
    assert await cache.get("key") == "value"


async def test_named_stores_isolate_data() -> None:
    manager = CacheManager(
        stores={
            "a": {"driver": "memory"},
            "b": {"driver": "memory"},
        },
        default="a",
    )
    await manager.store("a").put("shared_key", "from_a")
    await manager.store("b").put("shared_key", "from_b")
    assert await manager.store("a").get("shared_key") == "from_a"
    assert await manager.store("b").get("shared_key") == "from_b"


def test_unknown_store_raises() -> None:
    manager = CacheManager(stores={"only": {"driver": "memory"}})
    with pytest.raises(KeyError, match="nonexistent"):
        manager.store("nonexistent")


def test_unknown_driver_raises() -> None:
    manager = CacheManager(stores={"bad": {"driver": "nosql_magic"}})
    with pytest.raises(ValueError, match="Unknown cache driver"):
        manager.store("bad")


async def test_flush_all() -> None:
    manager = CacheManager(
        stores={
            "a": {"driver": "memory"},
            "b": {"driver": "memory"},
        },
        default="a",
    )
    await manager.store("a").put("k", "v")
    await manager.store("b").put("k", "v")
    await manager.flush_all()
    assert await manager.store("a").get("k") is None
    assert await manager.store("b").get("k") is None


def test_purge_forces_recreate() -> None:
    manager = CacheManager(
        stores={"main": {"driver": "memory"}},
        default="main",
    )
    first = manager.store("main")
    manager.purge("main")
    second = manager.store("main")
    assert first is not second


def test_extend_custom_driver() -> None:
    manager = CacheManager(
        stores={"custom": {"driver": "mock"}},
        default="custom",
    )
    manager.extend("mock", lambda cfg: MemoryCacheStore())
    cache = manager.store("custom")
    assert isinstance(cache, Cache)


def test_array_driver_alias() -> None:
    """'array' is an alias for 'memory', matching Laravel convention."""
    manager = CacheManager(stores={"arr": {"driver": "array"}})
    cache = manager.store("arr")
    assert isinstance(cache, Cache)


def test_default_store_property() -> None:
    manager = CacheManager(default="redis", stores={"redis": {"driver": "memory"}})
    assert manager.default_store == "redis"
