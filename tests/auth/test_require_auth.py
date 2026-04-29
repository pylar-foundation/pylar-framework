"""End-to-end tests for :class:`RequireAuthMiddleware`."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

from pylar.auth import (
    AuthMiddleware,
    Guard,
    RequireAuthMiddleware,
    current_user,
)
from pylar.foundation import (
    AppConfig,
    Application,
    Container,
    ServiceProvider,
)
from pylar.http import HttpKernel, Request, Response, json
from pylar.routing import Router


@dataclass(frozen=True)
class _AuthUser:
    id: int

    @property
    def auth_identifier(self) -> int:
        return self.id

    @property
    def auth_password_hash(self) -> str:
        return ""


class _HeaderGuard:
    """Test-only guard that authenticates from an ``X-User-Id`` header."""

    async def authenticate(self, request: Request) -> _AuthUser | None:
        raw = request.headers.get("x-user-id")
        if raw is None:
            return None
        try:
            return _AuthUser(id=int(raw))
        except ValueError:
            return None


async def _me(request: Request) -> Response:
    user = current_user()
    return json({"id": user.auth_identifier})


class _RouteProvider(ServiceProvider):
    def register(self, container: Container) -> None:
        container.singleton(Guard, _HeaderGuard)  # type: ignore[type-abstract]
        router = Router()
        protected = router.group(
            middleware=[AuthMiddleware, RequireAuthMiddleware],
        )
        protected.get("/me", _me)
        container.singleton(Router, lambda: router)


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = Application(
        base_path=Path("/tmp/pylar-require-auth-test"),
        config=AppConfig(
            name="require-auth-test",
            debug=True,
            providers=(_RouteProvider,),
        ),
    )
    await app.bootstrap()
    transport = httpx.ASGITransport(app=HttpKernel(app).asgi())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await app.shutdown()


async def test_authenticated_request_passes(client: httpx.AsyncClient) -> None:
    response = await client.get("/me", headers={"x-user-id": "1"})
    assert response.status_code == 200
    assert response.json() == {"id": 1}


async def test_anonymous_request_returns_401(client: httpx.AsyncClient) -> None:
    response = await client.get("/me")
    assert response.status_code == 401


async def test_invalid_user_id_returns_401(client: httpx.AsyncClient) -> None:
    response = await client.get("/me", headers={"x-user-id": "not-a-number"})
    # The guard returns None for unparseable ids, so the require-auth
    # middleware kicks in with 401 — exactly the same path as a missing
    # header.
    assert response.status_code == 401
