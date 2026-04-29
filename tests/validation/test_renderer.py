"""Tests for pluggable validation error renderer."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from pylar.foundation import AppConfig, Application, Container, ServiceProvider
from pylar.http import HttpKernel, Request, Response, json
from pylar.http.response import JsonResponse
from pylar.routing import Router
from pylar.validation import (
    DefaultValidationRenderer,
    RequestDTO,
    ValidationErrorRenderer,
)


class StrictInput(RequestDTO):
    name: str
    age: int


async def _create(request: Request, input: StrictInput) -> Response:
    return json({"name": input.name})


# -------------------------------------------------- custom renderer


class ProblemDetailsRenderer:
    """RFC 7807 style error renderer."""

    def render(self, errors: list[dict[str, Any]]) -> Response:
        return JsonResponse(
            content={
                "type": "about:blank",
                "title": "Validation Error",
                "status": 422,
                "detail": f"{len(errors)} field(s) failed validation",
                "errors": errors,
            },
            status_code=422,
        )


# -------------------------------------------------- providers


class _DefaultRoutes(ServiceProvider):
    def register(self, container: Container) -> None:
        router = Router()
        router.post("/create", _create)
        container.singleton(Router, lambda: router)


class _CustomRendererRoutes(ServiceProvider):
    def register(self, container: Container) -> None:
        router = Router()
        router.post("/create", _create)
        container.singleton(Router, lambda: router)
        container.singleton(
            ValidationErrorRenderer,  # type: ignore[type-abstract]
            ProblemDetailsRenderer,
        )


# -------------------------------------------------- fixtures


@pytest.fixture
async def default_client() -> AsyncIterator[httpx.AsyncClient]:
    app = Application(
        base_path=Path("/tmp/pylar-renderer-default"),
        config=AppConfig(name="renderer-default", debug=True, providers=(_DefaultRoutes,)),
    )
    await app.bootstrap()
    transport = httpx.ASGITransport(app=HttpKernel(app).asgi())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await app.shutdown()


@pytest.fixture
async def custom_client() -> AsyncIterator[httpx.AsyncClient]:
    app = Application(
        base_path=Path("/tmp/pylar-renderer-custom"),
        config=AppConfig(name="renderer-custom", debug=True, providers=(_CustomRendererRoutes,)),
    )
    await app.bootstrap()
    transport = httpx.ASGITransport(app=HttpKernel(app).asgi())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await app.shutdown()


# -------------------------------------------------- tests


async def test_default_renderer_returns_errors_key(
    default_client: httpx.AsyncClient,
) -> None:
    r = await default_client.post("/create", json={})
    assert r.status_code == 422
    body = r.json()
    assert "errors" in body
    assert isinstance(body["errors"], list)


async def test_custom_renderer_returns_problem_details(
    custom_client: httpx.AsyncClient,
) -> None:
    r = await custom_client.post("/create", json={})
    assert r.status_code == 422
    body = r.json()
    assert body["type"] == "about:blank"
    assert body["title"] == "Validation Error"
    assert "errors" in body


def test_default_renderer_standalone() -> None:
    renderer = DefaultValidationRenderer()
    response = renderer.render([{"loc": ["name"], "msg": "required", "type": "missing"}])
    assert response.status_code == 422
