"""Exceptions raised by the validation layer."""

from __future__ import annotations

from typing import Any


class ValidationError(Exception):
    """Raised when a request payload fails to validate against its DTO.

    Carries the structured error list pydantic produces so that the route
    compiler can render it as a 422 JSON response without losing field
    information.
    """

    def __init__(self, errors: list[dict[str, Any]]) -> None:
        self.errors = errors
        super().__init__(f"Validation failed with {len(errors)} error(s)")


class MalformedBodyError(ValidationError):
    """Raised when a request body cannot even be parsed (e.g. broken JSON)."""

    def __init__(self, detail: str) -> None:
        super().__init__([{"loc": ("body",), "msg": detail, "type": "body.malformed"}])
