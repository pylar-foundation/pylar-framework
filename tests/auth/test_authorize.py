"""Tests for authorize() middleware factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from pylar.auth import (
    AuthMiddleware,
    Gate,
    RequireAuthMiddleware,
    authorize,
)
from pylar.auth.contracts import Authenticatable, Guard
from pylar.foundation import AppConfig, Application, Container, ServiceProvider
from pylar.http import HttpKernel, Request, Response, json

# ------------------------------------------------ fake user & guard


class _FakeUser:
    def __init__(self, *, is_admin: bool = False) -> None:
        self.is_admin = is_admin

    @property
    def auth_identifier(self) -> int:
        return 1


class _HeaderGuard:
    """Resolve user from X-User header for testing."""

    async def authenticate(self, request: Request) -> Authenticatable | None:
        header = request.headers.get("x-user")
        if header == "admin":
            return _FakeUser(is_admin=True)  # type: ignore[return-value]
        if header == "user":
            return _FakeUser(is_admin=False)  # type: ignore[return-value]
        return None


# ------------------------------------------------ handlers


async def _dashboard(request: Request) -> Response:
    return json({"page": "admin-dashboard"})


async def _public(request: Request) -> Response:
    return json({"page": "public"})


# ------------------------------------------------ provider


class _Routes(ServiceProvider):
    def register(self, container: Container) -> None:
        from pylar.routing import Router

        gate = Gate()
        gate.define("access-admin", _check_admin)
        container.singleton(Gate, lambda: gate)
        container.singleton(Guard, _HeaderGuard)  # type: ignore[type-abstract]

        router = Router()
        router.get("/admin", _dashboard, middleware=[
            AuthMiddleware,
            RequireAuthMiddleware,
            authorize("access-admin"),
        ])
        router.get("/public", _public)
        container.singleton(Router, lambda: router)


async def _check_admin(user: object) -> bool:
    return getattr(user, "is_admin", False)


# ------------------------------------------------ fixtures


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = Application(
        base_path=Path("/tmp/pylar-authorize-test"),
        config=AppConfig(name="authorize-test", debug=True, providers=(_Routes,)),
    )
    await app.bootstrap()
    transport = httpx.ASGITransport(app=HttpKernel(app).asgi())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await app.shutdown()


# ------------------------------------------------ tests


async def test_authorize_allows_admin(client: httpx.AsyncClient) -> None:
    r = await client.get("/admin", headers={"x-user": "admin"})
    assert r.status_code == 200
    assert r.json()["page"] == "admin-dashboard"


async def test_authorize_denies_regular_user(client: httpx.AsyncClient) -> None:
    r = await client.get("/admin", headers={"x-user": "user"})
    assert r.status_code == 403


async def test_authorize_denies_anonymous(client: httpx.AsyncClient) -> None:
    r = await client.get("/admin")
    assert r.status_code == 401


async def test_public_route_not_affected(client: httpx.AsyncClient) -> None:
    r = await client.get("/public")
    assert r.status_code == 200


def test_authorize_returns_unique_class() -> None:
    cls1 = authorize("view")
    cls2 = authorize("edit")
    assert cls1 is not cls2
    assert cls1.ability == "view"
    assert cls2.ability == "edit"
