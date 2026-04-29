# cache/ — backlog

The Cache + Scheduling combo landed:

* atomic operations on the :class:`Cache` facade —
  ``increment(key, by=1)``, ``decrement(key, by=1)``, ``add(key,
  value, ttl=...)`` (set-if-absent). The :class:`MemoryCacheStore`
  serialises them through an asyncio mutex; persistent drivers will
  override the underlying store methods with native CAS / SETNX
  primitives once they ship.
* tagged groups via ``cache.tag("posts", "popular").put(...)`` and
  ``await cache.tag("posts").flush()`` to invalidate every key
  associated with a tag.
* :class:`CacheLock` distributed locks usable as ``async with``,
  with optional non-blocking ``acquire(blocking=False)`` and
  blocking-with-timeout. Backed by the same atomic ``add`` primitive
  the rest of the cache uses.

What is still on the wishlist:

## Persistent drivers

`FileCacheStore` (pickle blobs on disk) and `DatabaseCacheStore`
(SQLAlchemy ``pylar_cache`` table with built-in ``bootstrap()``)
landed alongside the in-memory driver. What is still on the wishlist:

* `RedisCacheStore` — string keys, JSON or msgpack values, native TTL
  via `EXPIRE`. Should override `add` / `increment` / `decrement` to
  delegate to `SETNX` / `INCRBY` so the atomic guarantees survive
  cross-process. Optional dep behind `pylar[cache-redis]`.

## Multiple stores

Some applications want a small in-memory cache for hot data and a
shared Redis cache for cross-instance work. Add named stores resolved
through a `CacheManager` that the container exposes:

```python
hot: Cache = container.make(CacheManager).store("memory")
shared: Cache = container.make(CacheManager).store("redis")
```

## `forever` shortcut

`Cache.forever(key, value)` for the common "no TTL" path. One-line
sugar over `await cache.put(key, value, ttl=None)` — worth adding
when the rest of the API is in heavier use.
