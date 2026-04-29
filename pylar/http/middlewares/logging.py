"""Structured request/response logging middleware.

Logs every request with method, path, status code, and duration in
a structured format suitable for log aggregation (JSON via Python's
stdlib :mod:`logging`). Pairs naturally with
:class:`RequestIdMiddleware` — when present, the log includes the
request ID for correlation.
"""

from __future__ import annotations

import logging
import time

from pylar.http.middleware import RequestHandler
from pylar.http.request import Request
from pylar.http.response import Response

_logger = logging.getLogger("pylar.http.request")


class LogRequestMiddleware:
    """Log method, path, status, and duration for every request.

    Place early in the middleware stack (after
    :class:`RequestIdMiddleware` if used) so the timing covers the
    full pipeline.
    """

    async def handle(
        self, request: Request, next_handler: RequestHandler
    ) -> Response:
        start = time.monotonic()
        response = await next_handler(request)
        duration_ms = (time.monotonic() - start) * 1000

        request_id = request.scope.get("request_id", "")
        _logger.info(
            "%s %s → %d (%.1fms)%s",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            f" [{request_id}]" if request_id else "",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round(duration_ms, 1),
                "request_id": request_id,
                "client": request.client.host if request.client else None,
            },
        )
        return response
