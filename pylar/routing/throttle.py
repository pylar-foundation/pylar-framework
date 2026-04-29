"""Cache-backed rate-limiting middleware.

The middleware is a small typed wrapper around :class:`pylar.cache.Cache`
that counts requests under a key derived from the client IP and the
route path. When the counter overflows the configured limit the
middleware short-circuits with HTTP 429 and a ``Retry-After`` header.

This is the per-route equivalent of the :class:`pylar.queue.RateLimited`
middleware on the queue side — both reach for the same atomic
``increment`` primitive on the cache facade.
"""

from __future__ import annotations

from pylar.cache.cache import Cache
from pylar.http.exceptions import HttpException
from pylar.http.middleware import RequestHandler
from pylar.http.request import Request
from pylar.http.response import Response


class TooManyRequests(HttpException):
    """HTTP 429 raised by :class:`ThrottleMiddleware` when the limit is hit."""

    def __init__(self, retry_after: int) -> None:
        super().__init__(
            status_code=429,
            detail=f"Too many requests. Retry after {retry_after}s.",
            headers={"Retry-After": str(retry_after)},
        )


class ThrottleMiddleware:
    """Limit requests to ``max_requests`` per ``window_seconds`` per client.

    The client identity defaults to the request's remote address. Override
    :meth:`identity_for` on a subclass to key by authenticated user id,
    API key, or any other request-derived value.
    """

    max_requests: int = 60
    window_seconds: int = 60
    key_prefix: str = "throttle"

    def __init__(self, cache: Cache) -> None:
        self._cache = cache

    def identity_for(self, request: Request) -> str:
        client = request.client
        if client is not None:
            return client.host
        return "anonymous"

    async def handle(
        self, request: Request, next_handler: RequestHandler
    ) -> Response:
        identity = self.identity_for(request)
        key = f"{self.key_prefix}:{identity}:{request.url.path}"
        try:
            # Single atomic call: INCRBY (+ EXPIRE NX on first hit) on
            # Redis, mutex-guarded get/put on the memory driver. We
            # cannot seed the counter with ``add(key, 0)`` first —
            # that path pickles the zero, and Redis INCRBY rejects
            # pickled bytes.
            count = await self._cache.increment(
                key, ttl=self.window_seconds,
            )
        except TypeError:
            return await next_handler(request)
        if count > self.max_requests:
            raise TooManyRequests(retry_after=self.window_seconds)
        return await next_handler(request)
