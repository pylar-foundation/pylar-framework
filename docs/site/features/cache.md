# Cache

Pylar's cache layer provides a `CacheStore` protocol with a high-level `Cache` facade for get/set, remember, tagging, and distributed locking.

## Configuration

Register a store in your service provider:

```python
from pylar.cache import Cache, CacheStore, MemoryCacheStore

# In your CacheServiceProvider.register():
container.singleton(CacheStore, MemoryCacheStore)
container.singleton(Cache, lambda c: Cache(c.make(CacheStore)))
```

## Basic Operations

```python
from pylar.cache import Cache

cache: Cache  # auto-wired via DI

await cache.put("user:42", user_data, ttl=3600)
data = await cache.get("user:42")           # returns None on miss
exists = await cache.has("user:42")         # bool
await cache.forget("user:42")               # delete one key
await cache.flush()                         # delete everything
```

## Remember (Get-or-Compute)

```python
posts = await cache.remember("posts:recent", ttl=300, factory=fetch_recent_posts)
```

If the key exists, the cached value is returned. Otherwise `factory` is awaited, the result is stored, and returned. This is the most common caching pattern.

## Atomic Add

```python
was_set = await cache.add("lock:import", "running", ttl=60)
if not was_set:
    return  # another process already holds the key
```

`add()` sets the key only if it does not already exist. Returns `True` on success.

## Increment / Decrement

```python
count = await cache.increment("page:views", by=1)
count = await cache.decrement("stock:item:99", by=1)
```

## Tagged Cache

Group related keys for bulk invalidation:

```python
tagged = cache.tag("posts", "feed")
await tagged.put("feed:main", feed_data, ttl=600)
await tagged.put("feed:trending", trending, ttl=600)

# Invalidate all keys in the tag group:
dropped = await tagged.flush()
```

## Distributed Locking

```python
from pylar.cache import CacheLock

async with cache.lock("import:csv", ttl=120):
    await run_import()
    # lock is released when the block exits
```

The lock retries acquisition every `retry_seconds` (default 0.1s). If `ttl` expires, the lock is auto-released to prevent deadlocks.

## CacheStore Protocol

Implement this protocol to add a custom backend (Redis, Memcached, etc.):

```python
from pylar.cache import CacheStore

class RedisCacheStore:
    async def get(self, key: str) -> Any: ...
    async def put(self, key: str, value: Any, *, ttl: int | None = None) -> None: ...
    async def forget(self, key: str) -> None: ...
    async def flush(self) -> None: ...
```

## Built-in Store

| Store | Backend | Use Case |
|---|---|---|
| `MemoryCacheStore` | In-process dict | Development, testing, single-process apps |

The memory store uses monotonic TTL tracking and runs lazy garbage collection every 100 writes.
