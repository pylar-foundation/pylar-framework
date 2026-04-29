"""Middleware that renders API-shaped errors for a group of routes.

Attach to any route / route group that should speak the ADR-0007 error
envelope instead of the default HTML-flow friendly shapes emitted by
:class:`pylar.routing.compiler.RoutesCompiler`.

The middleware catches :class:`ApiError`, :class:`ValidationError`, and
:class:`AuthorizationError`. Everything else propagates — the compiler's
default 500 handling still applies to unhandled exceptions.
"""

from __future__ import annotations

from pylar.api.errors import ApiError
from pylar.api.renderer import render_api_error
from pylar.auth.exceptions import AuthorizationError
from pylar.http.middleware import RequestHandler
from pylar.http.request import Request
from pylar.http.response import Response
from pylar.validation.exceptions import ValidationError


class ApiErrorMiddleware:
    """Render API-style JSON envelopes for caught domain exceptions."""

    async def handle(
        self, request: Request, next_handler: RequestHandler
    ) -> Response:
        try:
            return await next_handler(request)
        except (ApiError, ValidationError, AuthorizationError) as exc:
            return render_api_error(exc)
