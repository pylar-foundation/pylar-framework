"""Strip leading/trailing whitespace from every string value in the request body.

Catches the most common data-entry mistake — trailing spaces in form
fields and JSON payloads — before the DTO layer sees the data, so
validation rules like ``min_length=1`` don't pass on ``"   "``.

The middleware mutates ``request.scope["_body_override"]``; pylar's
DTO resolver checks for that key before reading the raw body. Fields
listed in :attr:`except_fields` are left untouched — passwords,
Markdown, and other values where whitespace is intentional.
"""

from __future__ import annotations

import json as _json
from typing import Any

from pylar.http.middleware import RequestHandler
from pylar.http.request import Request
from pylar.http.response import Response


class TrimStringsMiddleware:
    """Trim whitespace from JSON and form string values."""

    #: Field names that should *not* be trimmed (e.g. ``"password"``).
    except_fields: tuple[str, ...] = ("password", "password_confirmation")

    async def handle(
        self, request: Request, next_handler: RequestHandler
    ) -> Response:
        content_type = (
            request.headers.get("content-type", "").split(";")[0].strip().lower()
        )
        if content_type == "application/json":
            try:
                raw = await request.body()
                if raw:
                    data = _json.loads(raw)
                    if isinstance(data, dict):
                        trimmed = self._trim_dict(data)
                        request.scope["_body_override"] = _json.dumps(trimmed).encode("utf-8")
            except (_json.JSONDecodeError, UnicodeDecodeError):
                pass  # let the DTO layer surface the real error
        elif content_type in (
            "application/x-www-form-urlencoded",
            "multipart/form-data",
        ):
            # Form data is immutable in Starlette — trimming is handled
            # at the DTO level via pydantic's str_strip_whitespace, which
            # RequestDTO already enables. Nothing to do here.
            pass
        return await next_handler(request)

    def _trim_dict(self, data: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in data.items():
            if isinstance(value, str) and key not in self.except_fields:
                result[key] = value.strip()
            elif isinstance(value, dict):
                result[key] = self._trim_dict(value)
            elif isinstance(value, list):
                result[key] = self._trim_list(value)
            else:
                result[key] = value
        return result

    def _trim_list(self, items: list[Any]) -> list[Any]:
        result: list[Any] = []
        for item in items:
            if isinstance(item, str):
                result.append(item.strip())
            elif isinstance(item, dict):
                result.append(self._trim_dict(item))
            elif isinstance(item, list):
                result.append(self._trim_list(item))
            else:
                result.append(item)
        return result
