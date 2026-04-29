"""Attach a unique request ID to every request and response.

If the incoming request already carries an ``X-Request-Id`` header
(set by an upstream proxy or API gateway) the middleware reuses it
after sanitising the value (stripping CRLF to prevent log injection);
otherwise it generates a fresh UUID. The ID is stored in:

* ``request.scope["request_id"]`` — for controllers and error handlers.
* A :class:`contextvars.ContextVar` accessible via
  :func:`current_request_id` — for downstream code (database,
  queue, outbound HTTP) that does not have access to the request.

It is echoed back on the outgoing response so the caller can
correlate their request with server-side logs.
"""

from __future__ import annotations

import re
from contextvars import ContextVar
from uuid import uuid4

from pylar.http.middleware import RequestHandler
from pylar.http.request import Request
from pylar.http.response import Response

_current_request_id: ContextVar[str] = ContextVar(
    "pylar_request_id", default=""
)

#: Regex that strips anything that is not alphanumeric, dash, or
#: underscore — blocks CRLF log injection from user-supplied headers.
_SANITIZE_RE = re.compile(r"[^a-zA-Z0-9\-_]")


def current_request_id() -> str:
    """Return the active request ID, or ``""`` outside a request scope."""
    return _current_request_id.get()


class RequestIdMiddleware:
    """Generate or propagate a per-request trace ID."""

    #: Header name to read from the request and write onto the response.
    header: str = "X-Request-Id"

    async def handle(
        self, request: Request, next_handler: RequestHandler
    ) -> Response:
        raw = request.headers.get(self.header.lower()) or ""
        if raw:
            request_id = _SANITIZE_RE.sub("", raw)[:64]
        else:
            request_id = uuid4().hex
        request.scope["request_id"] = request_id
        token = _current_request_id.set(request_id)
        try:
            response = await next_handler(request)
        finally:
            _current_request_id.reset(token)
        response.headers[self.header] = request_id
        return response
