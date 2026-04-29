"""Cross-Origin Resource Sharing middleware.

Handles both *simple* CORS requests (adds the response headers) and
*preflight* ``OPTIONS`` requests (short-circuits with a 204 carrying
the ``Access-Control-Allow-*`` headers the browser needs before it
sends the real request).

Subclass and override the class-level attributes to tighten the
policy for production::

    class AppCors(CorsMiddleware):
        allowed_origins = ("https://app.example.com",)
        allow_credentials = True
        max_age = 600
"""

from __future__ import annotations

import logging

from pylar.http.middleware import RequestHandler
from pylar.http.request import Request
from pylar.http.response import Response

_logger = logging.getLogger("pylar.http.cors")


class CorsMiddleware:
    """Secure-by-default CORS middleware.

    ``allow_credentials`` defaults to ``False`` because the
    combination of ``credentials=True`` and ``origins=*`` violates
    the CORS spec (browsers reject it). Set ``allow_credentials=True``
    only when :attr:`allowed_origins` lists concrete origins.
    """

    #: Origins allowed to make cross-origin requests. ``("*",)`` means
    #: "any origin". List concrete origins for credentialed requests.
    allowed_origins: tuple[str, ...] = ("*",)

    #: HTTP methods the client may use.
    allowed_methods: tuple[str, ...] = (
        "GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS",
    )

    #: Request headers the client may send.
    allowed_headers: tuple[str, ...] = (
        "Accept", "Authorization", "Content-Type",
        "X-Requested-With", "X-CSRF-Token",
    )

    #: Response headers the browser is allowed to read.
    expose_headers: tuple[str, ...] = ()

    #: Whether the browser may send cookies / Authorization headers.
    #: Defaults to ``False``. Must list concrete origins when True.
    allow_credentials: bool = False

    #: How long (seconds) the browser may cache a preflight response.
    max_age: int = 86400

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        # Warn at class definition time if the subclass violates the
        # CORS spec.
        if getattr(cls, "allow_credentials", False) and "*" in getattr(
            cls, "allowed_origins", ()
        ):
            _logger.warning(
                "%s: allow_credentials=True with allowed_origins=('*',) "
                "violates the CORS spec — browsers will reject the response. "
                "List concrete origins instead.",
                cls.__qualname__,
            )

    async def handle(
        self, request: Request, next_handler: RequestHandler
    ) -> Response:
        origin = request.headers.get("origin", "")

        # Preflight — answer immediately without hitting the route.
        if request.method == "OPTIONS" and "access-control-request-method" in request.headers:
            response = Response(status_code=204)
            self._set_headers(response, origin)
            return response

        response = await next_handler(request)
        if origin:
            self._set_headers(response, origin)
        return response

    def _set_headers(self, response: Response, origin: str) -> None:
        allow_origin = origin if self._origin_allowed(origin) else ""
        if not allow_origin:
            return
        response.headers["Access-Control-Allow-Origin"] = allow_origin
        response.headers["Access-Control-Allow-Methods"] = ", ".join(self.allowed_methods)
        response.headers["Access-Control-Allow-Headers"] = ", ".join(self.allowed_headers)
        if self.expose_headers:
            response.headers["Access-Control-Expose-Headers"] = ", ".join(self.expose_headers)
        if self.allow_credentials:
            response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Max-Age"] = str(self.max_age)

    def _origin_allowed(self, origin: str) -> bool:
        if "*" in self.allowed_origins:
            return True
        return origin in self.allowed_origins
