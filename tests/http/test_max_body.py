"""Tests for :class:`MaxBodySizeMiddleware`."""

from __future__ import annotations

import httpx
import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from pylar.http.middlewares.max_body import MaxBodySizeMiddleware


async def _echo(request: Request) -> Response:
    body = await request.body()
    return Response(content=f"ok:{len(body)}", status_code=200)


def _build_app(max_size: int = 100) -> Starlette:
    return Starlette(
        routes=[Route("/upload", _echo, methods=["POST"])],
        middleware=[Middleware(MaxBodySizeMiddleware, max_size=max_size)],
    )


@pytest.fixture
def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_build_app(max_size=100)),
        base_url="http://test",
    )


class TestMaxBodySizeMiddleware:
    async def test_under_limit_passes(self, client: httpx.AsyncClient) -> None:
        resp = await client.post("/upload", content=b"x" * 50)
        assert resp.status_code == 200
        assert resp.text == "ok:50"

    async def test_at_limit_passes(self, client: httpx.AsyncClient) -> None:
        resp = await client.post("/upload", content=b"x" * 100)
        assert resp.status_code == 200
        assert resp.text == "ok:100"

    async def test_over_limit_returns_413(self, client: httpx.AsyncClient) -> None:
        resp = await client.post("/upload", content=b"x" * 101)
        assert resp.status_code == 413
        assert "too large" in resp.text.lower()

    async def test_get_always_passes(self) -> None:
        app = Starlette(
            routes=[Route("/", _echo, methods=["GET"])],
            middleware=[Middleware(MaxBodySizeMiddleware, max_size=1)],
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as c:
            resp = await c.get("/")
            assert resp.status_code == 200

    async def test_custom_max_size(self) -> None:
        app = _build_app(max_size=10)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as c:
            resp = await c.post("/upload", content=b"x" * 11)
            assert resp.status_code == 413
