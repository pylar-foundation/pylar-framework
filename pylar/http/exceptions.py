"""HTTP-layer exceptions used by pylar.

These wrap :class:`starlette.exceptions.HTTPException` so user code can raise
typed errors that the kernel converts to proper HTTP responses, without
importing Starlette directly.
"""

from __future__ import annotations

from starlette.exceptions import HTTPException as _StarletteHTTPException


class HttpException(_StarletteHTTPException):
    """Base class for HTTP errors raised from controllers and middleware."""

    def __init__(
        self,
        status_code: int,
        detail: str | None = None,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(
            status_code=status_code, detail=detail, headers=headers
        )


class NotFound(HttpException):
    def __init__(self, detail: str = "Not Found") -> None:
        super().__init__(status_code=404, detail=detail)


class MethodNotAllowed(HttpException):
    def __init__(self, detail: str = "Method Not Allowed") -> None:
        super().__init__(status_code=405, detail=detail)


class Unauthorized(HttpException):
    def __init__(self, detail: str = "Unauthorized") -> None:
        super().__init__(status_code=401, detail=detail)


class Forbidden(HttpException):
    def __init__(self, detail: str = "Forbidden") -> None:
        super().__init__(status_code=403, detail=detail)


class UnprocessableEntity(HttpException):
    def __init__(self, detail: str = "Unprocessable Entity") -> None:
        super().__init__(status_code=422, detail=detail)
