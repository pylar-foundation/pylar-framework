"""Route-level request timeout middleware.

Wraps the downstream handler in :func:`asyncio.wait_for` so that a
single slow request cannot pin a worker slot indefinitely. On timeout
the middleware returns a ``504 Gateway Timeout`` and lets the worker
accept the next request.

The middleware is intentionally route-level rather than ASGI-level
— different route groups often want different deadlines (a web
dashboard may tolerate 30 s, a webhook endpoint may require 5 s)
and a global timeout would force the lowest common denominator.

Usage::

    from pylar.http.middlewares import TimeoutMiddleware

    api = router.group(middleware=(TimeoutMiddleware(seconds=15),))

``seconds`` accepts a float for sub-second deadlines. The default
is 30 seconds, matching the database ``query_timeout`` default so
a request that runs a single query to completion never races the
handler timeout.
"""

from __future__ import annotations

import asyncio
import logging

from pylar.http.middleware import RequestHandler
from pylar.http.request import Request
from pylar.http.response import Response

_logger = logging.getLogger("pylar.http.timeout")


class TimeoutMiddleware:
    """Enforce a wall-clock deadline on request handlers."""

    #: Default deadline in seconds. Override via the constructor.
    DEFAULT_SECONDS: float = 30.0

    def __init__(self, *, seconds: float = DEFAULT_SECONDS) -> None:
        if seconds <= 0:
            raise ValueError(
                f"TimeoutMiddleware seconds must be > 0, got {seconds!r}"
            )
        self._seconds = seconds

    async def handle(
        self, request: Request, next_handler: RequestHandler
    ) -> Response:
        try:
            return await asyncio.wait_for(
                next_handler(request), timeout=self._seconds,
            )
        except TimeoutError:
            _logger.warning(
                "Request handler exceeded %.1fs deadline: %s %s",
                self._seconds,
                request.method,
                request.url.path,
            )
            return Response(
                content=f"Request exceeded {self._seconds:g}s deadline.",
                status_code=504,
                media_type="text/plain",
            )
