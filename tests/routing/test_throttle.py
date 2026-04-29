"""Tests for ThrottleMiddleware."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from pylar.cache import Cache, MemoryCacheStore
from pylar.foundation import AppConfig, Application, Container, ServiceProvider
from pylar.http import HttpKernel, Request, Response, json
from pylar.routing import Router, ThrottleMiddleware


class TightThrottle(ThrottleMiddleware):
    max_requests = 2
    window_seconds = 60


async def _ping(request: Request) -> Response:
    return json({"ok": True})


class _Routes(ServiceProvider):
    def register(self, container: Container) -> None:
        container.singleton(Cache, lambda: Cache(MemoryCacheStore()))
        router = Router()
        group = router.group(middleware=[TightThrottle])
        group.get("/ping", _ping)
        container.singleton(Router, lambda: router)


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = Application(
        base_path=Path("/tmp/pylar-throttle-test"),
        config=AppConfig(
            name="throttle-test",
            debug=True,
            providers=(_Routes,),
        ),
    )
    await app.bootstrap()
    transport = httpx.ASGITransport(app=HttpKernel(app).asgi())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await app.shutdown()


async def test_under_limit_passes_through(client: httpx.AsyncClient) -> None:
    assert (await client.get("/ping")).status_code == 200
    assert (await client.get("/ping")).status_code == 200


async def test_above_limit_returns_429(client: httpx.AsyncClient) -> None:
    await client.get("/ping")
    await client.get("/ping")
    response = await client.get("/ping")
    assert response.status_code == 429
    assert response.headers.get("retry-after") == "60"
