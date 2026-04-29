"""ASGI-level request body size limit.

Rejects requests whose body exceeds *max_size* bytes with a 413
``Content Too Large`` response before any route-level processing
reads the payload. This prevents memory exhaustion from oversized
uploads or malicious payloads.

Mounted automatically by :class:`HttpKernel` so applications get a
sensible default (10 MB) without explicit opt-in. Override the limit
by passing *max_size* to the constructor in a custom kernel.
"""

from __future__ import annotations

from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

#: Default body size limit: 10 megabytes.
DEFAULT_MAX_BODY_SIZE = 10 * 1024 * 1024


class MaxBodySizeMiddleware:
    """Return 413 when the incoming body exceeds *max_size* bytes.

    The middleware wraps the ASGI ``receive`` callable to count bytes
    as they arrive. When the accumulated size crosses the threshold,
    a plain-text 413 response is sent and the inner application is
    never invoked.

    Non-HTTP scopes (WebSocket, lifespan) are always passed through.
    ``GET``, ``HEAD``, ``OPTIONS`` requests skip the check entirely
    because they carry no body by convention.
    """

    _BODILESS_METHODS = frozenset({b"GET", b"HEAD", b"OPTIONS"})

    def __init__(
        self,
        app: ASGIApp,
        *,
        max_size: int = DEFAULT_MAX_BODY_SIZE,
    ) -> None:
        self.app = app
        self._max_size = max_size

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        raw_method = scope.get("method", "GET")
        method: bytes = (
            raw_method.encode() if isinstance(raw_method, str) else raw_method
        )
        if method in self._BODILESS_METHODS:
            await self.app(scope, receive, send)
            return

        received = 0
        exceeded = False

        async def limited_receive() -> Message:
            nonlocal received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                body: bytes = message.get("body", b"")
                received += len(body)
                if received > self._max_size:
                    exceeded = True
                    raise _BodyTooLargeError()
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _BodyTooLargeError:
            response = Response(
                content=(
                    f"Request body too large. "
                    f"Maximum allowed size is {self._max_size} bytes."
                ),
                status_code=413,
                media_type="text/plain",
            )
            await response(scope, receive, send)


class _BodyTooLargeError(Exception):
    """Internal signal — never escapes the middleware."""
