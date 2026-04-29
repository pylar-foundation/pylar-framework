"""ASGI-level rate limiter that fires before route matching.

Unlike :class:`ThrottleMiddleware` (which sits inside the route
pipeline and only fires on matched routes), this middleware is
mounted on the Starlette application itself. It counts *every*
incoming request — including requests to non-existent paths — so
DDoS attacks hitting random URLs are throttled before any route
matching, middleware construction, or database work happens.

Two buckets, one counter per bucket:

* **Anonymous** traffic — no session cookie, no ``Authorization``
  header. Keyed by **client IP**, capped at ``max_requests`` per
  window. Aggressive by design because this is where DDoS and
  scraping traffic lives.
* **Likely-authenticated** traffic — any request carrying either a
  session cookie *or* an ``Authorization`` header. Keyed by a
  **hash of the credential itself** — the session cookie value or
  the raw ``Authorization`` header — so two users behind the same
  NAT each get their own counter. Capped at
  ``max_requests * authenticated_multiplier``.

Detection is heuristic on purpose: the ASGI middleware runs before
the session layer opens the cookie, so we can't validate it. A
forged cookie still hits the raised cap, which is a rate-limit, not
a security boundary — the framework's real auth checks happen
downstream. We hash the credential before writing it into the Redis
key so the raw value never appears in cache logs or introspection.

Usage (in HttpKernel or a service provider)::

    from starlette.middleware import Middleware
    from pylar.http.middlewares.asgi_throttle import ASGIThrottleMiddleware

    app = Starlette(
        middleware=[Middleware(ASGIThrottleMiddleware, cache=cache)],
        ...
    )
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send


class ASGIThrottleMiddleware:
    """Global per-IP rate limiter at the ASGI transport level.

    Rejects with 429 before route matching, so random-path DDoS
    traffic never reaches the router or any pylar middleware.
    Applies a higher ceiling to traffic that looks authenticated —
    see the module docstring for the detection rules.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        cache: Any = None,
        container: Any = None,
        max_requests: int = 120,
        authenticated_multiplier: int = 10,
        window_seconds: int = 60,
        key_prefix: str = "asgi-throttle",
        session_cookie: str = "pylar_session_id",
    ) -> None:
        self.app = app
        self._cache = cache
        self._container = container
        self._max_requests = max_requests
        self._auth_multiplier = max(1, authenticated_multiplier)
        self._window_seconds = window_seconds
        self._key_prefix = key_prefix
        self._session_cookie = session_cookie

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        if scope["type"] != "http" or self._cache is None:
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        bucket, identity = self._classify(request)
        authenticated = bucket == "auth"
        limit = (
            self._max_requests * self._auth_multiplier
            if authenticated
            else self._max_requests
        )
        key = f"{self._key_prefix}:{bucket}:{identity}"

        try:
            count = await self._cache.increment(
                key, ttl=self._window_seconds,
            )
        except Exception:
            await self.app(scope, receive, send)
            return

        if count > limit:
            response = await self._build_rate_limited_response(request)
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)

    def _classify(self, request: Request) -> tuple[str, str]:
        """Pick the bucket + identity key for this request.

        Auth requests key by the credential itself (hashed), not by
        IP — two users sharing one NAT must not share a counter.
        Anon requests still key by IP since there's nothing better
        to identify them.
        """
        auth_header = request.headers.get("authorization", "")
        if auth_header:
            return "auth", "token:" + self._fingerprint(auth_header)
        cookie = request.cookies.get(self._session_cookie)
        if cookie:
            return "auth", "session:" + self._fingerprint(cookie)
        client = request.client
        ip = client.host if client else "unknown"
        return "anon", f"ip:{ip}"

    @staticmethod
    def _fingerprint(value: str) -> str:
        """Short SHA-256 of *value* — keeps raw credentials out of cache keys.

        16 hex chars (64 bits) is plenty for a collision-resistant
        rate-limit identifier without bloating the key for logging.
        """
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]

    async def _build_rate_limited_response(self, request: Request) -> Response:
        """Render a 429 using the same resolver chain as other errors.

        Content negotiation decides JSON vs HTML; the HTML path runs
        the framework's :func:`resolve_error_page` so a user-provided
        ``resources/views/errors/429.html`` or an explicit
        :func:`register_error_page` override is honoured even on this
        ASGI-level short-circuit. The ``Retry-After`` header is added
        after the body is built so both branches get it.
        """
        from pylar.http.error_handler import _wants_json
        from pylar.http.error_pages import resolve_error_page

        retry_header = {"Retry-After": str(self._window_seconds)}

        if _wants_json(request):
            body = json.dumps({"message": "Too Many Requests", "code": 429})
            return Response(
                content=body,
                status_code=429,
                headers=retry_header,
                media_type="application/json",
            )

        resp = await resolve_error_page(
            self._container,
            request,
            status_code=429,
            detail=None,
        )
        for k, v in retry_header.items():
            resp.headers[k] = v
        return resp
