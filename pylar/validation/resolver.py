"""Parse a :class:`Request` into typed DTO instances."""

from __future__ import annotations

import json as _json
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from pylar.http.request import Request
from pylar.validation.dto import CookieDTO, HeaderDTO, RequestDTO
from pylar.validation.exceptions import MalformedBodyError, ValidationError

_BODYLESS_METHODS = frozenset({"GET", "DELETE", "HEAD", "OPTIONS"})


async def resolve_header_dto[HeaderDtoT: HeaderDTO](
    dto_cls: type[HeaderDtoT], request: Request
) -> HeaderDtoT:
    """Build *dto_cls* from ``request.headers``.

    Header names are lower-cased so the DTO field declarations can use
    the canonical lower-case form (or rely on Field aliases for the
    same effect). Multi-value headers are joined the way Starlette
    presents them — pylar does not split, so DTOs that need lists must
    declare ``Sequence[str]`` and parse the value themselves.
    """
    raw = {key.lower(): value for key, value in request.headers.items()}
    try:
        return dto_cls.model_validate(raw)
    except PydanticValidationError as exc:
        raise ValidationError(_serialize_errors(exc)) from exc


async def resolve_cookie_dto[CookieDtoT: CookieDTO](
    dto_cls: type[CookieDtoT], request: Request
) -> CookieDtoT:
    """Build *dto_cls* from ``request.cookies``."""
    raw = dict(request.cookies)
    try:
        return dto_cls.model_validate(raw)
    except PydanticValidationError as exc:
        raise ValidationError(_serialize_errors(exc)) from exc


async def resolve_dto[DtoT: RequestDTO](dto_cls: type[DtoT], request: Request) -> DtoT:
    """Build *dto_cls* from *request*.

    The data source depends on the HTTP method:

    * ``GET``/``DELETE``/``HEAD``/``OPTIONS`` → ``request.query_params``
    * Anything else with ``application/json`` → JSON body
    * Anything else with form content types → ``request.form()``
    * Otherwise → an empty dict (which will surface missing-field errors
      from pydantic, the desired behaviour)
    """
    raw = await _extract_raw(request)
    try:
        return dto_cls.model_validate(raw)
    except PydanticValidationError as exc:
        raise ValidationError(_serialize_errors(exc)) from exc


async def _extract_raw(request: Request) -> dict[str, Any]:
    if request.method in _BODYLESS_METHODS:
        return _flatten_multidict(request.query_params)

    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()

    if content_type == "application/json":
        try:
            body = await request.body()
        except Exception as exc:  # pragma: no cover - extremely rare
            raise MalformedBodyError(f"Could not read request body: {exc}") from exc
        if not body:
            return {}
        try:
            payload = _json.loads(body)
        except _json.JSONDecodeError as exc:
            raise MalformedBodyError(f"Invalid JSON body: {exc.msg}") from exc
        if not isinstance(payload, dict):
            raise MalformedBodyError("JSON body must be an object")
        return payload

    if content_type in ("application/x-www-form-urlencoded", "multipart/form-data"):
        form = await request.form()
        return _flatten_multidict(form)

    return {}


def _flatten_multidict(multidict: Any) -> dict[str, Any]:
    """Convert Starlette's multidict-like collection to a plain dict.

    Repeated keys collapse to a list, single keys stay as scalars — pydantic
    handles both shapes natively for ``list[X]`` and ``X`` annotations.
    """
    result: dict[str, Any] = {}
    for key in multidict.keys():
        values = multidict.getlist(key)
        result[key] = values if len(values) > 1 else values[0]
    return result


def _serialize_errors(exc: PydanticValidationError) -> list[dict[str, Any]]:
    """Project a pydantic ValidationError into pylar's wire format."""
    serialised: list[dict[str, Any]] = []
    for err in exc.errors(include_url=False):
        serialised.append(
            {
                "loc": list(err.get("loc", ())),
                "msg": err.get("msg", ""),
                "type": err.get("type", ""),
            }
        )
    return serialised
