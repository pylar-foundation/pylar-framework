"""Tests for the cache atomic operations, tagged groups, and locks."""

from __future__ import annotations

import asyncio

import pytest

from pylar.cache import (
    Cache,
    CacheLock,
    CacheLockError,
    MemoryCacheStore,
    TaggedCache,
)


@pytest.fixture
def cache() -> Cache:
    return Cache(MemoryCacheStore())


# ----------------------------------------------------------- atomic ops


async def test_increment_starts_from_zero(cache: Cache) -> None:
    assert await cache.increment("counter") == 1
    assert await cache.increment("counter") == 2
    assert await cache.get("counter") == 2


async def test_increment_with_explicit_step(cache: Cache) -> None:
    await cache.put("counter", 10)
    assert await cache.increment("counter", by=5) == 15


async def test_decrement_inverts_increment(cache: Cache) -> None:
    await cache.put("counter", 10)
    assert await cache.decrement("counter") == 9
    assert await cache.decrement("counter", by=4) == 5


async def test_increment_rejects_non_integer_existing_value(cache: Cache) -> None:
    await cache.put("counter", "not a number")
    with pytest.raises(TypeError, match="Cannot increment"):
        await cache.increment("counter")


async def test_increment_rejects_bool(cache: Cache) -> None:
    await cache.put("flag", True)
    with pytest.raises(TypeError):
        await cache.increment("flag")


async def test_add_sets_when_missing(cache: Cache) -> None:
    assert await cache.add("k", "first") is True
    assert await cache.get("k") == "first"


async def test_add_skips_when_present(cache: Cache) -> None:
    await cache.put("k", "first")
    assert await cache.add("k", "second") is False
    assert await cache.get("k") == "first"


async def test_add_with_ttl(cache: Cache) -> None:
    assert await cache.add("k", "v", ttl=60) is True


# ----------------------------------------------------------- tagged cache


async def test_tag_returns_tagged_cache_instance(cache: Cache) -> None:
    tagged = cache.tag("posts")
    assert isinstance(tagged, TaggedCache)
    assert tagged.tags == ("posts",)


async def test_tag_requires_at_least_one_name(cache: Cache) -> None:
    with pytest.raises(ValueError, match="at least one tag"):
        cache.tag()


async def test_tagged_put_routes_to_underlying_cache(cache: Cache) -> None:
    await cache.tag("posts").put("post:1", {"title": "hi"})
    assert await cache.get("post:1") == {"title": "hi"}


async def test_tagged_flush_drops_keys_for_that_tag(cache: Cache) -> None:
    await cache.tag("posts").put("post:1", "a")
    await cache.tag("posts").put("post:2", "b")
    await cache.put("untagged", "stays")

    removed = await cache.tag("posts").flush()
    assert removed == 2
    assert await cache.get("post:1") is None
    assert await cache.get("post:2") is None
    assert await cache.get("untagged") == "stays"


async def test_tagged_flush_with_unknown_tag_returns_zero(cache: Cache) -> None:
    removed = await cache.tag("ghost").flush()
    assert removed == 0


async def test_tagged_keys_can_belong_to_multiple_tags(cache: Cache) -> None:
    await cache.tag("posts", "popular").put("post:42", "shared")
    assert await cache.get("post:42") == "shared"

    # Flushing one tag drops the key, even though it was also under
    # another tag — Laravel's behaviour matches this expectation.
    await cache.tag("posts").flush()
    assert await cache.get("post:42") is None


async def test_full_cache_flush_clears_tag_index(cache: Cache) -> None:
    await cache.tag("posts").put("post:1", "x")
    await cache.flush()
    # The tag index should be empty now — a subsequent flush via the
    # same tag must report zero removals because everything is gone.
    assert await cache.tag("posts").flush() == 0


# --------------------------------------------------------------- locks


async def test_lock_acquires_and_releases(cache: Cache) -> None:
    lock = cache.lock("k", ttl=10)
    assert lock.held is False
    assert await lock.acquire() is True
    assert lock.held is True
    await lock.release()
    assert lock.held is False


async def test_lock_returns_correct_type(cache: Cache) -> None:
    assert isinstance(cache.lock("x"), CacheLock)


async def test_lock_blocks_other_acquirers(cache: Cache) -> None:
    first = cache.lock("k", ttl=10, retry_seconds=0.01)
    second = cache.lock("k", ttl=10, retry_seconds=0.01)

    await first.acquire()
    # Non-blocking second acquire fails immediately.
    assert await second.acquire(blocking=False) is False

    await first.release()
    assert await second.acquire(blocking=False) is True


async def test_lock_blocking_with_timeout_raises(cache: Cache) -> None:
    held = cache.lock("k", ttl=10, retry_seconds=0.01)
    waiter = cache.lock("k", ttl=10, retry_seconds=0.01)

    await held.acquire()
    with pytest.raises(CacheLockError, match="Could not acquire"):
        await waiter.acquire(blocking=True, timeout=0.05)


async def test_lock_blocking_succeeds_when_released(cache: Cache) -> None:
    held = cache.lock("k", ttl=10, retry_seconds=0.01)
    waiter = cache.lock("k", ttl=10, retry_seconds=0.01)

    await held.acquire()

    async def _release_after_delay() -> None:
        await asyncio.sleep(0.05)
        await held.release()

    release_task = asyncio.create_task(_release_after_delay())
    await waiter.acquire(timeout=1.0)
    await release_task
    assert waiter.held is True
    await waiter.release()


async def test_lock_release_is_idempotent(cache: Cache) -> None:
    lock = cache.lock("k")
    await lock.release()  # never acquired — no-op
    await lock.acquire()
    await lock.release()
    await lock.release()  # already released — no-op


async def test_lock_async_context_manager(cache: Cache) -> None:
    async with cache.lock("k", ttl=10) as lock:
        assert lock.held
    assert lock.held is False


async def test_two_locks_serialise_via_context_manager(cache: Cache) -> None:
    """Sanity check the realistic critical-section pattern."""
    log: list[str] = []

    async def task(name: str) -> None:
        async with cache.lock("section", ttl=10, retry_seconds=0.01):
            log.append(f"{name}:enter")
            await asyncio.sleep(0.02)
            log.append(f"{name}:leave")

    await asyncio.gather(task("a"), task("b"))
    # Both tasks ran but their critical sections did not overlap.
    assert log == [
        "a:enter", "a:leave", "b:enter", "b:leave",
    ] or log == [
        "b:enter", "b:leave", "a:enter", "a:leave",
    ]
