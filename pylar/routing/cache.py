"""Per-route HTTP response caching middleware.

Caches the full response body and headers for GET requests, serving
subsequent hits directly from the :class:`~pylar.cache.Cache` facade
without touching the controller. Non-GET methods always pass through
and invalidate the cache entry for the same path.

Attach via the fluent builder::

    router.get("/posts", PostController.index).cache(seconds=60)

or via middleware directly::

    class ShortCache(CacheResponseMiddleware):
        seconds = 30

    router.get("/feed", FeedController.index, middleware=[ShortCache])
"""

from __future__ import annotations

import hashlib
import json as _json
from typing import ClassVar

from pylar.cache.cache import Cache
from pylar.http.middleware import RequestHandler
from pylar.http.request import Request
from pylar.http.response import Response


class CacheResponseMiddleware:
    """Cache full HTTP responses for ``seconds`` per unique path.

    Only **GET** requests are cached. Mutating methods (POST, PUT,
    PATCH, DELETE) pass through and **invalidate** the cache entry for
    the same path so stale reads don't survive writes.

    The cache key includes the full path with query string so
    ``/posts?page=1`` and ``/posts?page=2`` are stored separately.

    Responses with a status code outside 200-299 are never cached.
    """

    seconds: ClassVar[int] = 60
    key_prefix: ClassVar[str] = "route_cache"

    def __init__(self, cache: Cache) -> None:
        self._cache = cache

    def _cache_key(self, request: Request) -> str:
        url = str(request.url).split("?", 1)
        path = url[0]
        query = url[1] if len(url) > 1 else ""
        raw = f"{path}?{query}" if query else path
        digest = hashlib.md5(raw.encode(), usedforsecurity=False).hexdigest()
        return f"{self.key_prefix}:{digest}"

    async def handle(
        self, request: Request, next_handler: RequestHandler
    ) -> Response:
        key = self._cache_key(request)

        # Mutating methods: pass through and invalidate.
        if request.method not in ("GET", "HEAD"):
            response = await next_handler(request)
            await self._cache.forget(key)
            return response

        # Try cache hit.
        cached = await self._cache.get(key)
        if cached is not None:
            entry = _json.loads(cached)
            return Response(
                content=entry["body"].encode("utf-8"),
                status_code=entry["status"],
                headers=entry["headers"],
            )

        # Cache miss: run handler, cache if 2xx.
        response = await next_handler(request)

        if 200 <= response.status_code < 300:
            body = bytes(response.body)

            headers = dict(response.headers)
            headers["Cache-Control"] = f"public, max-age={self.seconds}"

            entry = _json.dumps({
                "body": body.decode("utf-8"),
                "status": response.status_code,
                "headers": headers,
            })
            await self._cache.put(key, entry, ttl=self.seconds)

            return Response(
                content=body,
                status_code=response.status_code,
                headers=headers,
            )

        return response
