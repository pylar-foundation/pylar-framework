"""API layer — pydantic-driven resources, pagination, OpenAPI (ADR-0007).

The module consolidates the pieces a typed JSON API needs:

* :class:`Page` — generic pagination envelope built on
  :class:`pylar.database.Paginator`.
* :class:`ApiError` — the exception type API routes raise to produce a
  stable error envelope.
* :class:`ApiErrorMiddleware` — catches :class:`ApiError`,
  :class:`pylar.validation.ValidationError`, and
  :class:`pylar.auth.AuthorizationError` and renders them into the
  phase-7 JSON shape.
* :class:`ApiServiceProvider` — wires the above into the container and
  installs the auto-serialiser hook that turns pydantic BaseModel
  return values into JsonResponse.

Controllers that return :class:`pydantic.BaseModel` (or a list thereof,
or a :class:`Page`) are auto-serialised. Controllers that need full
control return :class:`pylar.http.Response` explicitly — unchanged.
"""

from pylar.api.errors import ApiError
from pylar.api.middleware import ApiErrorMiddleware
from pylar.api.openapi import generate_openapi
from pylar.api.pagination import Page, PageLinks, PageMeta
from pylar.api.provider import ApiDocsConfig, ApiServiceProvider
from pylar.api.renderer import render_api_error, render_api_response

__all__ = [
    "ApiDocsConfig",
    "ApiError",
    "ApiErrorMiddleware",
    "ApiServiceProvider",
    "Page",
    "PageLinks",
    "PageMeta",
    "generate_openapi",
    "render_api_error",
    "render_api_response",
]
