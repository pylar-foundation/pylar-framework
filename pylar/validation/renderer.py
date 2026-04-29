"""Pluggable validation error rendering.

The default renderer produces ``{"errors": [{"loc", "msg", "type"}]}``
which matches the structure most API clients expect. Teams that want
RFC 7807 problem-details or a custom envelope can bind their own
implementation::

    class ProblemDetailsRenderer(ValidationErrorRenderer):
        def render(self, errors: list[dict[str, Any]]) -> Response:
            return JsonResponse(
                content={
                    "type": "about:blank",
                    "title": "Validation Error",
                    "status": 422,
                    "errors": errors,
                },
                status_code=422,
                headers={"Content-Type": "application/problem+json"},
            )

    # In a service provider:
    container.singleton(ValidationErrorRenderer, ProblemDetailsRenderer)
"""

from __future__ import annotations

from typing import Any, Protocol

from pylar.http.response import JsonResponse, Response


class ValidationErrorRenderer(Protocol):
    """Strategy for turning validation errors into an HTTP response."""

    def render(self, errors: list[dict[str, Any]]) -> Response: ...


class DefaultValidationRenderer:
    """The default renderer — ``{"errors": [...]}`` with status 422."""

    def render(self, errors: list[dict[str, Any]]) -> Response:
        return JsonResponse(content={"errors": errors}, status_code=422)
