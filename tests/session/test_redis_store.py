"""Tests for the Redis-backed session store (pickle serialisation)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from pylar.session.stores.redis import RedisSessionStore

pytest.importorskip("fakeredis")
from fakeredis.aioredis import FakeRedis


@pytest.fixture
async def store() -> AsyncIterator[RedisSessionStore]:
    client = FakeRedis()
    yield RedisSessionStore(client, prefix="test:session:")
    await client.aclose()


async def test_round_trip(store: RedisSessionStore) -> None:
    await store.write("sid1", {"user_id": 42}, ttl_seconds=60)
    data = await store.read("sid1")
    assert data == {"user_id": 42}


async def test_read_missing_returns_none(store: RedisSessionStore) -> None:
    assert await store.read("nope") is None


async def test_destroy_removes_key(store: RedisSessionStore) -> None:
    await store.write("sid2", {"x": 1}, ttl_seconds=60)
    await store.destroy("sid2")
    assert await store.read("sid2") is None


async def test_ttl_is_applied(store: RedisSessionStore) -> None:
    await store.write("sid3", {"k": "v"}, ttl_seconds=1)
    # fakeredis respects TTL on read if we wait past it.
    await asyncio.sleep(1.1)
    assert await store.read("sid3") is None


async def test_overwrite_replaces_data(store: RedisSessionStore) -> None:
    await store.write("sid4", {"a": 1}, ttl_seconds=60)
    await store.write("sid4", {"b": 2}, ttl_seconds=60)
    assert await store.read("sid4") == {"b": 2}


async def test_prefix_namespaces_keys(store: RedisSessionStore) -> None:
    """Two stores with different prefixes on the same client are isolated."""
    client = store._client
    other = RedisSessionStore(client, prefix="other:")
    await store.write("shared", {"who": "store1"}, ttl_seconds=60)
    await other.write("shared", {"who": "store2"}, ttl_seconds=60)
    assert (await store.read("shared"))["who"] == "store1"
    assert (await other.read("shared"))["who"] == "store2"


async def test_corrupt_data_returns_none(store: RedisSessionStore) -> None:
    """If someone hand-writes garbage into Redis the store does not crash."""
    await store._client.set("test:session:bad", b"not-pickle!!!")
    assert await store.read("bad") is None


@dataclass(frozen=True)
class _UserSnapshot:
    id: int
    name: str
    joined: datetime


async def test_stores_arbitrary_python_objects(store: RedisSessionStore) -> None:
    """Pickle lets the session carry datetime, dataclass, etc."""
    now = datetime.now(UTC)
    user = _UserSnapshot(id=42, name="Alice", joined=now)
    await store.write("obj", {"user": user, "tags": frozenset({"a", "b"})}, ttl_seconds=60)
    data = await store.read("obj")
    assert data is not None
    assert data["user"] == user
    assert data["user"].joined == now
    assert isinstance(data["tags"], frozenset)
