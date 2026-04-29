"""Behavioural tests for :func:`pylar.validation.resolve_dto`."""

from __future__ import annotations

import json

import pytest
from pydantic import Field
from pydantic import ValidationError as PydanticValidationError

from pylar.http import Request
from pylar.validation import (
    MalformedBodyError,
    RequestDTO,
    ValidationError,
    resolve_dto,
)


class CreateUserDTO(RequestDTO):
    email: str
    name: str = Field(min_length=1, max_length=100)
    age: int = 0


class SearchDTO(RequestDTO):
    q: str
    limit: int = 10


def _request(
    method: str,
    *,
    body: bytes = b"",
    headers: list[tuple[bytes, bytes]] | None = None,
    path: str = "/",
    query: bytes = b"",
) -> Request:
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": headers or [],
        "query_string": query,
        "scheme": "http",
        "server": ("test", 80),
    }
    body_sent = {"value": False}

    async def receive() -> dict[str, object]:
        if body_sent["value"]:
            return {"type": "http.disconnect"}
        body_sent["value"] = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive)  # type: ignore[arg-type]


async def test_post_json_body_parses_into_dto() -> None:
    payload = {"email": "alice@example.com", "name": "Alice", "age": 30}
    request = _request(
        "POST",
        body=json.dumps(payload).encode(),
        headers=[(b"content-type", b"application/json")],
    )
    dto = await resolve_dto(CreateUserDTO, request)
    assert dto == CreateUserDTO(email="alice@example.com", name="Alice", age=30)


async def test_get_query_params_parse_into_dto() -> None:
    request = _request("GET", query=b"q=python&limit=25")
    dto = await resolve_dto(SearchDTO, request)
    assert dto.q == "python"
    assert dto.limit == 25


async def test_get_query_default_values_apply() -> None:
    request = _request("GET", query=b"q=django")
    dto = await resolve_dto(SearchDTO, request)
    assert dto.limit == 10


async def test_invalid_json_raises_malformed_body() -> None:
    request = _request(
        "POST",
        body=b"not json",
        headers=[(b"content-type", b"application/json")],
    )
    with pytest.raises(MalformedBodyError) as exc_info:
        await resolve_dto(CreateUserDTO, request)
    assert exc_info.value.errors[0]["type"] == "body.malformed"


async def test_json_array_body_rejected() -> None:
    request = _request(
        "POST",
        body=b"[1,2,3]",
        headers=[(b"content-type", b"application/json")],
    )
    with pytest.raises(MalformedBodyError):
        await resolve_dto(CreateUserDTO, request)


async def test_validation_error_carries_structured_errors() -> None:
    request = _request(
        "POST",
        body=json.dumps({"email": "x", "name": ""}).encode(),
        headers=[(b"content-type", b"application/json")],
    )
    with pytest.raises(ValidationError) as exc_info:
        await resolve_dto(CreateUserDTO, request)
    errors = exc_info.value.errors
    fields = {tuple(err["loc"]) for err in errors}
    assert ("name",) in fields  # min_length violation
    # email is plain str so it accepts "x" — only name fails


async def test_extra_field_rejected_by_strict_dto() -> None:
    request = _request(
        "POST",
        body=json.dumps(
            {"email": "x@y", "name": "Bob", "unknown": "field"}
        ).encode(),
        headers=[(b"content-type", b"application/json")],
    )
    with pytest.raises(ValidationError) as exc_info:
        await resolve_dto(CreateUserDTO, request)
    locations = {tuple(e["loc"]) for e in exc_info.value.errors}
    assert ("unknown",) in locations


async def test_form_urlencoded_body_parses() -> None:
    body = b"q=python&limit=5"
    request = _request(
        "POST",
        body=body,
        headers=[
            (b"content-type", b"application/x-www-form-urlencoded"),
            (b"content-length", str(len(body)).encode()),
        ],
    )
    dto = await resolve_dto(SearchDTO, request)
    assert dto == SearchDTO(q="python", limit=5)


async def test_dto_is_frozen() -> None:
    dto = CreateUserDTO(email="x@y", name="A")
    with pytest.raises(PydanticValidationError):
        dto.email = "z"  # type: ignore[misc]


async def test_empty_body_with_json_content_type() -> None:
    request = _request(
        "POST",
        body=b"",
        headers=[(b"content-type", b"application/json")],
    )
    with pytest.raises(ValidationError):
        await resolve_dto(CreateUserDTO, request)
