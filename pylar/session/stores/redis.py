"""Redis-backed session store.

Sessions map naturally onto Redis strings with a server-side TTL:

* ``write`` → ``SET key payload EX ttl``
* ``read``  → ``GET key`` (expired keys vanish automatically)
* ``destroy`` → ``DEL key``

The driver uses the ``redis.asyncio`` client shipped by ``redis>=5.0``
(install through the ``pylar[session-redis]`` extra). All keys are
namespaced under a configurable prefix so session data coexists with
cache data, queue data, or anything else the application stores in
the same Redis instance.

The payload is serialised with :mod:`pickle` (protocol 5) so the
session can carry arbitrary Python objects — ``datetime`` instances,
frozen dataclasses, ORM snapshots, anything the application puts
there. Security-wise this is safe because session data is
*server-controlled*: only the application writes to Redis, and the
session id in the cookie is HMAC-signed so an attacker cannot point
it at a crafted payload without the secret key.
"""

from __future__ import annotations

from typing import Any

from pylar.support.serializer import dumps, safe_loads

try:
    from redis.asyncio import Redis
except ImportError:  # pragma: no cover
    raise ImportError(
        "RedisSessionStore requires the 'redis' package. "
        "Install it with: pip install 'pylar[session-redis]'"
    ) from None


class RedisSessionStore:
    """Session driver backed by a Redis server.

    *client* is a ``redis.asyncio.Redis`` instance — the caller owns
    its lifecycle (connection pool, closing). The store only calls
    ``get``, ``set``, and ``delete``; it never issues ``FLUSHDB`` or
    ``KEYS`` so it is safe to point at a shared Redis that other
    services also use.

    *prefix* namespaces every key so sessions do not collide with
    cache entries or queue records that live in the same database::

        store = RedisSessionStore(
            Redis.from_url("redis://localhost:6379/0"),
            prefix="session:",
        )
    """

    def __init__(
        self,
        client: Redis,
        *,
        prefix: str = "pylar:session:",
    ) -> None:
        self._client = client
        self._prefix = prefix

    async def read(self, session_id: str) -> dict[str, Any] | None:
        raw = await self._client.get(self._key(session_id))
        if raw is None:
            return None
        try:
            payload = safe_loads(raw)
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
        return payload

    async def write(
        self,
        session_id: str,
        data: dict[str, Any],
        *,
        ttl_seconds: int,
    ) -> None:
        encoded = dumps(data)
        await self._client.set(
            self._key(session_id), encoded, ex=ttl_seconds
        )

    async def destroy(self, session_id: str) -> None:
        await self._client.delete(self._key(session_id))

    def _key(self, session_id: str) -> str:
        return f"{self._prefix}{session_id}"
