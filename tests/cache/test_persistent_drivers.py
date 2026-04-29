"""Tests for FileCacheStore and DatabaseCacheStore."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from pylar.cache import Cache, DatabaseCacheStore, FileCacheStore

# ----------------------------------------------------------- FileCacheStore


@pytest.fixture
def file_store(tmp_path: Path) -> FileCacheStore:
    return FileCacheStore(tmp_path / "cache")


async def test_file_store_round_trip(file_store: FileCacheStore) -> None:
    await file_store.put("key", {"hello": "world"})
    assert await file_store.get("key") == {"hello": "world"}


async def test_file_store_get_missing_returns_none(file_store: FileCacheStore) -> None:
    assert await file_store.get("missing") is None


async def test_file_store_forget_removes_entry(file_store: FileCacheStore) -> None:
    await file_store.put("k", "v")
    await file_store.forget("k")
    assert await file_store.get("k") is None


async def test_file_store_flush_clears_everything(file_store: FileCacheStore) -> None:
    await file_store.put("a", 1)
    await file_store.put("b", 2)
    await file_store.flush()
    assert await file_store.get("a") is None
    assert await file_store.get("b") is None


async def test_file_store_ttl_expires(file_store: FileCacheStore) -> None:
    await file_store.put("k", "v", ttl=0)
    await asyncio.sleep(0.01)
    assert await file_store.get("k") is None


async def test_file_store_handles_unsafe_keys(file_store: FileCacheStore) -> None:
    # SHA-256 keying means traversal characters can never escape the
    # sandbox directory.
    await file_store.put("../../etc/passwd", "shouldnt-escape")
    assert await file_store.get("../../etc/passwd") == "shouldnt-escape"


async def test_file_store_through_cache_facade(file_store: FileCacheStore) -> None:
    cache = Cache(file_store)
    assert await cache.add("k", "first") is True
    assert await cache.add("k", "second") is False
    assert await cache.get("k") == "first"


# ------------------------------------------------------- DatabaseCacheStore


@pytest.fixture
async def db_store() -> AsyncIterator[DatabaseCacheStore]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    store = DatabaseCacheStore(engine)
    await store.bootstrap()
    try:
        yield store
    finally:
        await engine.dispose()


async def test_db_store_round_trip(db_store: DatabaseCacheStore) -> None:
    await db_store.put("key", {"hello": "world"})
    assert await db_store.get("key") == {"hello": "world"}


async def test_db_store_overwrites_existing(db_store: DatabaseCacheStore) -> None:
    await db_store.put("key", "first")
    await db_store.put("key", "second")
    assert await db_store.get("key") == "second"


async def test_db_store_forget(db_store: DatabaseCacheStore) -> None:
    await db_store.put("key", "v")
    await db_store.forget("key")
    assert await db_store.get("key") is None


async def test_db_store_flush(db_store: DatabaseCacheStore) -> None:
    await db_store.put("a", 1)
    await db_store.put("b", 2)
    await db_store.flush()
    assert await db_store.get("a") is None
    assert await db_store.get("b") is None


async def test_db_store_ttl_expires(db_store: DatabaseCacheStore) -> None:
    await db_store.put("k", "v", ttl=0)
    await asyncio.sleep(0.01)
    assert await db_store.get("k") is None


async def test_db_store_through_cache_facade(db_store: DatabaseCacheStore) -> None:
    cache = Cache(db_store)
    assert await cache.add("counter", 0) is True
    val = await cache.increment("counter", by=5)
    assert val == 5
    assert await cache.get("counter") == 5
