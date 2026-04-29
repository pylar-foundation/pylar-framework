"""Tests for LoginThrottleMiddleware — auth-specific rate limiting."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from pylar.auth.middleware import LoginThrottleMiddleware
from pylar.cache import Cache, MemoryCacheStore
from pylar.foundation import AppConfig, Application, Container, ServiceProvider
from pylar.http import HttpKernel, Request, Response, json
from pylar.routing import Router


async def _login(request: Request) -> Response:
    return json({"token": "ok"})


async def _public(request: Request) -> Response:
    return json({"page": "home"})


class _Routes(ServiceProvider):
    def register(self, container: Container) -> None:
        container.singleton(Cache, lambda: Cache(MemoryCacheStore()))
        router = Router()
        auth = router.group(middleware=[LoginThrottleMiddleware])
        auth.post("/login", _login)
        router.get("/public", _public)
        container.singleton(Router, lambda: router)


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = Application(
        base_path=Path("/tmp/pylar-login-throttle-test"),
        config=AppConfig(
            name="login-throttle-test",
            debug=True,
            providers=(_Routes,),
        ),
    )
    await app.bootstrap()
    transport = httpx.ASGITransport(app=HttpKernel(app).asgi())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await app.shutdown()


async def test_within_limit_passes(client: httpx.AsyncClient) -> None:
    for _ in range(5):
        r = await client.post("/login")
        assert r.status_code == 200


async def test_sixth_request_returns_429(client: httpx.AsyncClient) -> None:
    for _ in range(5):
        await client.post("/login")
    r = await client.post("/login")
    assert r.status_code == 429
    assert r.headers.get("retry-after") == "60"


async def test_public_route_not_throttled(client: httpx.AsyncClient) -> None:
    """LoginThrottle only applies to the auth group, not public routes."""
    for _ in range(10):
        r = await client.get("/public")
        assert r.status_code == 200


async def test_different_paths_have_separate_counters(
    client: httpx.AsyncClient,
) -> None:
    """Each path gets its own counter, so /login and /register are independent."""
    # Exhaust /login limit
    for _ in range(5):
        await client.post("/login")
    assert (await client.post("/login")).status_code == 429
    # /public still works (different group, no throttle)
    assert (await client.get("/public")).status_code == 200
