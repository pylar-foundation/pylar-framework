"""``ApiError`` — the exception type API endpoints raise to shape the envelope.

Controllers raise :class:`ApiError` with a semantic ``code`` (snake_case
machine-readable identifier) and a human-readable ``message``; optional
``details`` carry per-field or per-item diagnostic data. The renderer
in :mod:`pylar.api.renderer` turns the instance into the envelope
declared by ADR-0007.

The exception is the API analogue of
:class:`pylar.validation.ValidationError` and
:class:`pylar.auth.AuthorizationError`, which are still caught and
translated to the same envelope — one error shape regardless of where
the failure originated.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


class ApiError(Exception):
    """Semantic error raised by API endpoints.

    ``status_code`` defaults to 400 (Bad Request). Use 404 for
    not-found, 409 for conflict, 422 for validation problems that
    are richer than what pydantic alone can express, and 503 for
    backend-unavailable paths.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        details: Sequence[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details: list[dict[str, Any]] = list(details) if details else []
