"""Tests for CacheResponseMiddleware and the .cache() fluent builder."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from pylar.cache import Cache, MemoryCacheStore
from pylar.foundation import AppConfig, Application, Container, ServiceProvider
from pylar.http import HttpKernel, Request, Response, json
from pylar.routing import CacheResponseMiddleware, Router

_call_count = 0


async def _expensive(request: Request) -> Response:
    global _call_count
    _call_count += 1
    return json({"count": _call_count})


async def _mutate(request: Request) -> Response:
    return json({"ok": True})


class ShortCache(CacheResponseMiddleware):
    seconds = 5


class _Routes(ServiceProvider):
    def register(self, container: Container) -> None:
        container.singleton(Cache, lambda: Cache(MemoryCacheStore()))
        router = Router()
        # Fluent .cache() API
        router.get("/cached", _expensive).cache(seconds=10)
        # Middleware class directly
        router.get("/short", _expensive, middleware=[ShortCache])
        # Uncached
        router.get("/fresh", _expensive)
        # POST to invalidate
        router.post("/cached", _mutate, middleware=[ShortCache])
        container.singleton(Router, lambda: router)


@pytest.fixture(autouse=True)
def _reset_counter() -> None:
    global _call_count
    _call_count = 0


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = Application(
        base_path=Path("/tmp/pylar-cache-test"),
        config=AppConfig(
            name="cache-test",
            debug=True,
            providers=(_Routes,),
        ),
    )
    await app.bootstrap()
    transport = httpx.ASGITransport(app=HttpKernel(app).asgi())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await app.shutdown()


async def test_cache_hit_returns_same_response(client: httpx.AsyncClient) -> None:
    r1 = await client.get("/cached")
    r2 = await client.get("/cached")
    assert r1.json()["count"] == r2.json()["count"]
    assert r2.headers.get("cache-control") == "public, max-age=10"


async def test_cache_miss_calls_handler(client: httpx.AsyncClient) -> None:
    r1 = await client.get("/cached")
    assert r1.json()["count"] == 1


async def test_uncached_route_always_calls_handler(client: httpx.AsyncClient) -> None:
    r1 = await client.get("/fresh")
    r2 = await client.get("/fresh")
    assert r1.json()["count"] != r2.json()["count"]


async def test_post_invalidates_cache(client: httpx.AsyncClient) -> None:
    r1 = await client.get("/cached")
    count_before = r1.json()["count"]
    await client.post("/cached")
    r2 = await client.get("/cached")
    count_after = r2.json()["count"]
    assert count_after > count_before


async def test_different_query_strings_cached_separately(
    client: httpx.AsyncClient,
) -> None:
    r1 = await client.get("/cached?page=1")
    r2 = await client.get("/cached?page=2")
    assert r1.json()["count"] != r2.json()["count"]


async def test_non_200_not_cached(client: httpx.AsyncClient) -> None:
    # 404 should not be cached
    r1 = await client.get("/nonexistent")
    r2 = await client.get("/nonexistent")
    # Both should be 404 and not cached
    assert r1.status_code == 404
    assert r2.status_code == 404
