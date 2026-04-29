"""The :class:`Cache` facade — high-level API over a :class:`CacheStore`."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from pylar.cache.lock import CacheLock
from pylar.cache.store import CacheStore

T = TypeVar("T")


class Cache:
    """Convenience wrapper that controllers and services depend on.

    The wrapper exists so that drivers can stay minimal — they only
    implement four methods on :class:`CacheStore` — while user code
    enjoys the higher-level operations the application layer expects:
    presence checks, get-or-compute, atomic counters, tagged groups,
    and distributed locks. Resolved through the container; the bound
    store is configured by the application's service provider.

    Atomic operations
    -----------------

    :meth:`add`, :meth:`increment`, and :meth:`decrement` are
    *application-atomic*. They serialise correctly inside one process
    because asyncio gives them an uninterrupted slice between awaits,
    but they are **not** SQL ``UPDATE … SET`` style atomic against a
    persistent backend. A future Redis driver should override the
    relevant store methods with native ``INCR`` / ``SETNX`` calls so
    cluster-wide guarantees match.
    """

    def __init__(self, store: CacheStore) -> None:
        self._store = store
        self._mutex = asyncio.Lock()
        self._tag_index: dict[str, set[str]] = {}

    # ----------------------------------------------------------- basic ops

    async def get(self, key: str) -> Any:
        return await self._store.get(key)

    async def put(self, key: str, value: Any, *, ttl: int | None = None) -> None:
        await self._store.put(key, value, ttl=ttl)

    async def forget(self, key: str) -> None:
        await self._store.forget(key)

    async def flush(self) -> None:
        await self._store.flush()
        self._tag_index.clear()

    async def forever(self, key: str, value: Any) -> None:
        """Store *value* with no expiration (equivalent to ``put(ttl=None)``)."""
        await self._store.put(key, value, ttl=None)

    async def has(self, key: str) -> bool:
        return await self._store.get(key) is not None

    async def remember(
        self,
        key: str,
        *,
        ttl: int | None,
        factory: Callable[[], Awaitable[T]],
    ) -> T:
        """Return the cached value, or compute and store it on miss."""
        cached: Any = await self._store.get(key)
        if cached is not None:
            return cached  # type: ignore[no-any-return]
        value = await factory()
        await self._store.put(key, value, ttl=ttl)
        return value

    async def remember_with_lock(
        self,
        key: str,
        *,
        ttl: int | None,
        factory: Callable[[], Awaitable[T]],
        lock_ttl: int = 30,
    ) -> T:
        """Like :meth:`remember`, but only one caller computes on miss.

        When multiple concurrent requests miss the cache at the same
        time, a naive ``remember`` lets every one of them execute the
        factory — the classic *cache stampede* (thundering herd). This
        variant acquires a distributed :class:`CacheLock` before calling
        *factory*, so only the winner computes while the others wait
        for the result to land in the cache.

        *lock_ttl* controls how long the lock is held (seconds). It
        should be longer than the expected factory execution time.
        """
        cached: Any = await self._store.get(key)
        if cached is not None:
            return cached  # type: ignore[no-any-return]
        async with self.lock(f"{key}:stampede", ttl=lock_ttl):
            # Double-check after acquiring the lock — another caller
            # may have populated the cache while we were waiting.
            cached = await self._store.get(key)
            if cached is not None:
                return cached  # type: ignore[no-any-return]
            value = await factory()
            await self._store.put(key, value, ttl=ttl)
            return value

    # --------------------------------------------------------- atomic ops

    async def add(
        self,
        key: str,
        value: Any,
        *,
        ttl: int | None = None,
    ) -> bool:
        """Set *key* only if it is not already present.

        Returns ``True`` when the value was stored and ``False`` when
        an existing entry blocked the write. Used by :class:`CacheLock`
        as the underlying claim primitive.

        When the bound store exposes a native ``add`` method (e.g.
        :class:`RedisCacheStore` backed by ``SETNX``) the facade
        delegates to it directly so the guarantee is cross-process.
        """
        native = getattr(self._store, "add", None)
        if native is not None:
            return bool(await native(key, value, ttl=ttl))
        async with self._mutex:
            existing = await self._store.get(key)
            if existing is not None:
                return False
            await self._store.put(key, value, ttl=ttl)
            return True

    async def increment(
        self, key: str, by: int = 1, *, ttl: int | None = None,
    ) -> int:
        """Atomically bump the integer value at *key* by *by*.

        Missing keys are treated as zero. The new value is returned so
        callers can use the same call to read the post-increment count.
        Non-integer values trigger a :class:`TypeError` rather than a
        silent string concatenation.

        When *ttl* is passed and the key did not exist before this
        call, the TTL is applied atomically — this is the primitive
        throttle counters rely on to start a fresh rate-limit window
        on the first hit. Subsequent calls on the same key preserve
        the existing TTL.

        When the bound store exposes a native ``increment`` method
        (e.g. :class:`RedisCacheStore` via ``INCRBY``) the facade
        delegates to it for cross-process atomicity.
        """
        native = getattr(self._store, "increment", None)
        if native is not None:
            return int(await native(key, by, ttl=ttl))
        async with self._mutex:
            current = await self._store.get(key)
            is_new = current is None
            if current is None:
                current = 0
            if not isinstance(current, int) or isinstance(current, bool):
                raise TypeError(
                    f"Cannot increment {key!r}: existing value is "
                    f"{type(current).__name__}, not int"
                )
            new_value = current + by
            # Only pass ttl when the key is being created so repeat
            # increments don't extend the rate-limit window.
            await self._store.put(
                key, new_value, ttl=ttl if is_new else None,
            )
            return new_value

    async def decrement(self, key: str, by: int = 1) -> int:
        """Atomically lower the integer value at *key* by *by*."""
        native = getattr(self._store, "decrement", None)
        if native is not None:
            return int(await native(key, by))
        return await self.increment(key, -by)

    # ----------------------------------------------------------- tagging

    def tag(self, *tags: str) -> TaggedCache:
        """Return a :class:`TaggedCache` view bound to *tags*.

        Writes through the view are tracked under each tag. Calling
        :meth:`TaggedCache.flush` then drops every key tagged with any
        of the listed names. Reads through the view are pass-throughs
        — there is no per-tag namespacing.
        """
        if not tags:
            raise ValueError("Cache.tag() requires at least one tag name")
        return TaggedCache(self, tags)

    # ------------------------------------------------------------- locks

    def lock(
        self,
        key: str,
        *,
        ttl: int = 60,
        retry_seconds: float = 0.1,
    ) -> CacheLock:
        """Return a :class:`CacheLock` for *key* — usable as ``async with``."""
        return CacheLock(self, key, ttl=ttl, retry_seconds=retry_seconds)

    # ------------------------------------------------------------------ tag internals

    def _track_tags(self, key: str, tags: tuple[str, ...]) -> None:
        for tag in tags:
            self._tag_index.setdefault(tag, set()).add(key)

    async def _flush_tags(self, tags: tuple[str, ...]) -> int:
        keys_to_drop: set[str] = set()
        for tag in tags:
            keys_to_drop.update(self._tag_index.pop(tag, set()))
        for key in keys_to_drop:
            await self._store.forget(key)
        return len(keys_to_drop)


class TaggedCache:
    """A scoped view over :class:`Cache` that tracks writes against tags.

    Returned by :meth:`Cache.tag`. Writes register the key against
    every supplied tag, so :meth:`flush` can drop them in one go::

        await cache.tag("posts").put("post:1", post)
        await cache.tag("posts").put("post:2", other)

        # Invalidate everything tagged "posts" in one call:
        await cache.tag("posts").flush()
    """

    def __init__(self, cache: Cache, tags: tuple[str, ...]) -> None:
        self._cache = cache
        self._tags = tags

    @property
    def tags(self) -> tuple[str, ...]:
        return self._tags

    async def get(self, key: str) -> Any:
        return await self._cache.get(key)

    async def put(self, key: str, value: Any, *, ttl: int | None = None) -> None:
        self._cache._track_tags(key, self._tags)
        await self._cache.put(key, value, ttl=ttl)

    async def forget(self, key: str) -> None:
        await self._cache.forget(key)

    async def flush(self) -> int:
        """Drop every key associated with any of this view's tags.

        Returns the number of keys removed so callers can react to a
        no-op flush (typically a sign that the tag was misspelled).
        """
        return await self._cache._flush_tags(self._tags)
