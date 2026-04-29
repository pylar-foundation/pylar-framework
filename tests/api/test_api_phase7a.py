"""Tests for the API phase-7a foundations (ADR-0007).

Covers:
* Auto-serialisation of pydantic return values through the routing
  compiler (both function handlers and controller methods).
* ``ApiErrorMiddleware`` translating :class:`ApiError`,
  :class:`ValidationError`, and :class:`AuthorizationError` into the
  phase-7 JSON envelope.
* ``Page.from_paginator`` shape and numeric bookkeeping.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from pydantic import BaseModel

from pylar.api import ApiError, ApiErrorMiddleware, Page
from pylar.api.renderer import render_api_error, render_api_response
from pylar.auth.exceptions import AuthorizationError
from pylar.database.paginator import Paginator
from pylar.foundation import Container, ServiceProvider
from pylar.http.response import JsonResponse, Response
from pylar.routing import Router
from pylar.testing import create_test_app, http_client
from pylar.validation.exceptions import ValidationError

# --------------------------------------------------------------- resources


class _PostResource(BaseModel):
    id: int
    title: str


# ---------------------------------------------------- render_api_response


def test_render_api_response_passes_through_response() -> None:
    r = JsonResponse(content={"x": 1})
    assert render_api_response(r) is r


def test_render_api_response_wraps_base_model() -> None:
    result = render_api_response(_PostResource(id=1, title="A"))
    assert isinstance(result, Response)
    assert result.status_code == 200


def test_render_api_response_wraps_list_of_models() -> None:
    result = render_api_response([
        _PostResource(id=1, title="A"),
        _PostResource(id=2, title="B"),
    ])
    assert isinstance(result, Response)


# --------------------------------------------------------- render_api_error


def test_render_api_error_shapes_api_error() -> None:
    exc = ApiError("not_found", "Post not found.", status_code=404)
    resp = render_api_error(exc)
    assert resp.status_code == 404
    import json
    body = json.loads(resp.body.decode())
    assert body == {
        "error": {
            "code": "not_found",
            "message": "Post not found.",
            "details": [],
        }
    }


def test_render_api_error_shapes_validation_error() -> None:
    exc = ValidationError([
        {"loc": ("body", "title"), "msg": "Field required", "type": "missing"}
    ])
    resp = render_api_error(exc)
    assert resp.status_code == 422
    import json
    body = json.loads(resp.body.decode())
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["details"][0]["field"] == "body.title"


def test_render_api_error_shapes_authorization_error() -> None:
    exc = AuthorizationError("update", detail="Not allowed")
    resp = render_api_error(exc)
    assert resp.status_code == 403
    import json
    body = json.loads(resp.body.decode())
    assert body["error"]["code"] == "authorization_error"
    assert body["error"]["details"] == [{"ability": "update"}]


# ------------------------------------------------------- Page[T] envelope


def test_page_from_paginator_builds_envelope() -> None:
    paginator = Paginator(
        items=[object(), object()],
        total=17,
        per_page=5,
        current_page=2,
        path="/posts",
    )
    resources = [_PostResource(id=1, title="A"), _PostResource(id=2, title="B")]
    page: Page[_PostResource] = Page.from_paginator(paginator, resources)

    assert page.meta.page == 2
    assert page.meta.total == 17
    assert page.meta.total_pages == 4
    assert page.links.next is not None  # page 3 exists
    assert page.links.prev is not None  # page 1 exists
    assert page.links.self_ is not None


def test_page_from_paginator_first_page_has_no_prev() -> None:
    paginator = Paginator(items=[], total=0, per_page=10, current_page=1, path="/x")
    page: Page[_PostResource] = Page.from_paginator(paginator, [])
    assert page.links.prev is None
    assert page.links.next is None
    assert page.meta.total_pages == 1


# ----------------------------------------------- end-to-end through Router


async def _auto_model() -> _PostResource:
    return _PostResource(id=42, title="hi")


async def _auto_list() -> list[_PostResource]:
    return [
        _PostResource(id=1, title="a"),
        _PostResource(id=2, title="b"),
    ]


async def _raise_api_error() -> _PostResource:
    raise ApiError("nope", "gone", status_code=410)


async def _raise_auth() -> _PostResource:
    raise AuthorizationError("edit", detail="forbidden")


class _ApiRoutesProvider(ServiceProvider):
    def register(self, container: Container) -> None:
        router = Router()
        router.get("/auto-model", _auto_model)
        router.get("/auto-list", _auto_list)
        router.get(
            "/raise-api-error", _raise_api_error, middleware=[ApiErrorMiddleware]
        )
        router.get("/raise-auth", _raise_auth, middleware=[ApiErrorMiddleware])
        container.singleton(Router, lambda: router)


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = create_test_app(providers=[_ApiRoutesProvider])
    async with http_client(app) as c:
        yield c


async def test_route_auto_serialises_base_model(
    client: httpx.AsyncClient,
) -> None:
    r = await client.get("/auto-model")
    assert r.status_code == 200
    assert r.json() == {"id": 42, "title": "hi"}


async def test_route_auto_serialises_list_of_models(
    client: httpx.AsyncClient,
) -> None:
    r = await client.get("/auto-list")
    assert r.status_code == 200
    assert r.json() == [{"id": 1, "title": "a"}, {"id": 2, "title": "b"}]


async def test_api_middleware_renders_api_error(
    client: httpx.AsyncClient,
) -> None:
    r = await client.get("/raise-api-error")
    assert r.status_code == 410
    assert r.json() == {
        "error": {"code": "nope", "message": "gone", "details": []}
    }


async def test_api_middleware_renders_authorization_error(
    client: httpx.AsyncClient,
) -> None:
    r = await client.get("/raise-auth")
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "authorization_error"
