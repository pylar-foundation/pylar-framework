"""HTTP response types used throughout pylar.

These are thin re-exports of Starlette's response classes plus a small set of
typed helper constructors for common cases. The intent is that controllers
return one of these types directly — there is no automatic conversion of
arbitrary return values, because implicit serialisation hides errors.
"""

from __future__ import annotations

from typing import Any

from starlette.responses import HTMLResponse as _HTMLResponse
from starlette.responses import JSONResponse as _JSONResponse
from starlette.responses import PlainTextResponse as _PlainTextResponse
from starlette.responses import RedirectResponse as _RedirectResponse
from starlette.responses import Response as _Response


class Response(_Response):
    """Base HTTP response. See :class:`starlette.responses.Response`."""


# The four specialised responses inherit from BOTH ``Response`` (so
# ``isinstance(x, Response)`` and the routing return-type checks hold) and
# the corresponding Starlette subclass (so we keep its rendering behaviour
# unchanged). Both branches share ``starlette.responses.Response`` as their
# common ancestor, which makes Python's C3 linearisation accept the layout.


class JsonResponse(Response, _JSONResponse):
    """JSON response with the standard ``application/json`` media type."""


class HtmlResponse(Response, _HTMLResponse):
    """HTML response — used by view rendering."""


class PlainTextResponse(Response, _PlainTextResponse):
    """Plain text response."""


class RedirectResponse(Response, _RedirectResponse):
    """HTTP redirect (default 307 — preserves method and body)."""


def json(payload: Any, *, status: int = 200) -> JsonResponse:
    """Construct a :class:`JsonResponse` with *payload* and *status*."""
    return JsonResponse(content=payload, status_code=status)


def text(body: str, *, status: int = 200) -> PlainTextResponse:
    """Construct a plain text response."""
    return PlainTextResponse(content=body, status_code=status)


def html(body: str, *, status: int = 200) -> HtmlResponse:
    """Construct an HTML response."""
    return HtmlResponse(content=body, status_code=status)


def redirect(url: str, *, status: int = 302) -> RedirectResponse:
    """Construct a redirect response. Defaults to 302 Found."""
    return RedirectResponse(url=url, status_code=status)


def no_content() -> Response:
    """Construct an empty 204 No Content response."""
    return Response(status_code=204)


__all__ = [
    "HtmlResponse",
    "JsonResponse",
    "PlainTextResponse",
    "RedirectResponse",
    "Response",
    "html",
    "json",
    "no_content",
    "redirect",
    "text",
]
