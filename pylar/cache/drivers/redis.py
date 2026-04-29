"""Redis-backed cache store.

Implements the :class:`CacheStore` Protocol using Redis strings with
server-side TTL. Install through the ``pylar[cache-redis]`` extra
which pulls in ``redis>=5.0``.

Unlike the in-memory and file stores, the Redis driver overrides the
atomic primitives — ``add`` (SETNX), ``increment`` (INCRBY),
``decrement`` (DECRBY) — with native Redis commands so the
guarantees survive cross-process access. The :class:`Cache` facade
detects these methods on the store and delegates to them instead of
using its own asyncio-mutex path.

Values are serialised with :mod:`pickle` (protocol 5) so the cache
can carry arbitrary Python objects — the same rationale as the
session layer.
"""

from __future__ import annotations

import pickle
from typing import Any

from pylar.support.serializer import dumps, safe_loads

try:
    from redis.asyncio import Redis
except ImportError:  # pragma: no cover
    raise ImportError(
        "RedisCacheStore requires the 'redis' package. "
        "Install it with: pip install 'pylar[cache-redis]'"
    ) from None


class RedisCacheStore:
    """Cache driver backed by a Redis server.

    *client* is a ``redis.asyncio.Redis`` instance — the caller owns
    its lifecycle. *prefix* namespaces every key so cache data does
    not collide with sessions, queues, or anything else in the same
    Redis database.

    Usage::

        from redis.asyncio import Redis
        from pylar.cache.drivers.redis import RedisCacheStore

        store = RedisCacheStore(
            Redis.from_url("redis://localhost:6379/0"),
            prefix="cache:",
        )
    """

    def __init__(
        self,
        client: Redis,
        *,
        prefix: str = "pylar:cache:",
    ) -> None:
        self._client = client
        self._prefix = prefix

    # ----------------------------------------------------------- Protocol

    async def get(self, key: str) -> Any:
        raw = await self._client.get(self._key(key))
        if raw is None:
            return None
        try:
            return safe_loads(raw)
        except (pickle.UnpicklingError, EOFError):
            return None

    async def put(self, key: str, value: Any, *, ttl: int | None = None) -> None:
        data = dumps(value)
        if ttl is not None:
            await self._client.set(self._key(key), data, ex=ttl)
        else:
            await self._client.set(self._key(key), data)

    async def forget(self, key: str) -> None:
        await self._client.delete(self._key(key))

    async def flush(self) -> None:
        pattern = f"{self._prefix}*"
        cursor: int = 0
        while True:
            cursor, keys = await self._client.scan(cursor, match=pattern, count=100)
            if keys:
                await self._client.delete(*keys)
            if cursor == 0:
                break

    # ------------------------------------------------- native atomics

    async def add(self, key: str, value: Any, *, ttl: int | None = None) -> bool:
        """SET-if-absent via Redis ``SET ... NX [EX]``.

        Returns ``True`` when the key was set, ``False`` when it
        already existed. Fully atomic — the NX and EX flags are
        applied in a single command so there is no race between
        setting the key and attaching the TTL.
        """
        data = dumps(value)
        if ttl is not None:
            result = await self._client.set(
                self._key(key), data, nx=True, ex=ttl
            )
        else:
            result = await self._client.set(
                self._key(key), data, nx=True
            )
        return result is not None

    async def increment(
        self, key: str, by: int = 1, *, ttl: int | None = None,
    ) -> int:
        """Atomic ``INCRBY``, optionally seeding a TTL on first hit.

        If the key does not exist Redis creates it with value 0 and
        then increments, which matches the :class:`Cache` facade's
        "missing key = 0" semantics.

        When *ttl* is passed the operation runs in a pipeline with
        ``EXPIRE ... NX`` so a brand-new key gets its rate-limit
        window without overriding an already-configured TTL on an
        existing counter. That primitive is what
        :class:`ThrottleMiddleware` and queue ``RateLimited``
        middleware depend on to avoid drifting expiration windows.

        Note: the Redis value must have been stored as a bare integer
        (not pickled) for INCRBY to work. Callers that used
        ``put(key, 42)`` (pickled) will get a Redis error — counters
        must always be created via ``increment`` from the start.
        """
        redis_key = self._key(key)
        if ttl is None:
            return int(await self._client.incrby(redis_key, by))
        async with self._client.pipeline(transaction=True) as pipe:
            pipe.incrby(redis_key, by)
            # EXPIRE ... NX only sets the TTL when none exists — so a
            # running window is not extended by every increment.
            pipe.expire(redis_key, ttl, nx=True)
            results = await pipe.execute()
        return int(results[0])

    async def decrement(self, key: str, by: int = 1) -> int:
        """Atomic ``DECRBY``."""
        return int(await self._client.decrby(self._key(key), by))

    # -------------------------------------------------------- internals

    def _key(self, key: str) -> str:
        return f"{self._prefix}{key}"
