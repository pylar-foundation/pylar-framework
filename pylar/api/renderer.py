"""Convert API exceptions and pydantic return values into HTTP responses.

The module owns two symmetric concerns:

* :func:`render_api_error` turns any of :class:`ApiError`,
  :class:`pylar.validation.ValidationError`, or
  :class:`pylar.auth.AuthorizationError` into the phase-7 JSON envelope.
* :func:`render_api_response` recognises a pydantic-shaped return
  value (``BaseModel``, ``list[BaseModel]``, :class:`Page`) and wraps
  it in a :class:`JsonResponse` so controllers can return domain
  objects without hand-calling ``json(...)`` themselves.

Both helpers are pure functions so they can be invoked from the
routing compiler, from middleware, and from tests without an
application bootstrap.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from pylar.api.errors import ApiError
from pylar.auth.exceptions import AuthorizationError
from pylar.http.response import JsonResponse, Response
from pylar.validation.exceptions import ValidationError


def render_api_error(exc: Exception) -> JsonResponse:
    """Render *exc* into the ADR-0007 envelope.

    Unknown exception types bubble up; the caller is expected to have
    already filtered by class. The three recognised types are listed
    in the signature for clarity — pass anything else and you'll get
    a ``TypeError``.
    """
    if isinstance(exc, ApiError):
        return JsonResponse(
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                }
            },
            status_code=exc.status_code,
        )
    if isinstance(exc, ValidationError):
        return JsonResponse(
            content={
                "error": {
                    "code": "validation_error",
                    "message": "The given data was invalid.",
                    "details": [
                        {
                            "field": ".".join(
                                str(p) for p in err.get("loc", ())
                            ),
                            "message": err.get("msg", ""),
                        }
                        for err in exc.errors
                    ],
                }
            },
            status_code=422,
        )
    if isinstance(exc, AuthorizationError):
        return JsonResponse(
            content={
                "error": {
                    "code": "authorization_error",
                    "message": exc.detail,
                    "details": [{"ability": exc.ability}],
                }
            },
            status_code=403,
        )
    raise TypeError(
        f"render_api_error does not know how to render {type(exc).__name__}"
    )


def render_api_response(result: Any) -> Response:
    """Wrap a pydantic-shaped *result* in a :class:`JsonResponse`.

    Pass-through behaviour:

    * ``Response`` (or any subclass) — returned unchanged. Controllers
      that build their own response keep doing so.
    * ``BaseModel`` — serialised via ``model_dump(mode="json")``.
    * ``list`` of ``BaseModel`` — serialised element-wise.
    * anything else — returned as-is; the caller decides what to do.
    """
    if isinstance(result, Response):
        return result
    if isinstance(result, BaseModel):
        return JsonResponse(content=result.model_dump(mode="json"))
    if isinstance(result, list) and result and all(
        isinstance(item, BaseModel) for item in result
    ):
        return JsonResponse(
            content=[item.model_dump(mode="json") for item in result]
        )
    return result  # type: ignore[no-any-return]
