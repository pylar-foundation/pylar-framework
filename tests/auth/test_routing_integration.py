"""End-to-end auth tests: AuthMiddleware + Gate + 403 rendering."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

from pylar.auth import (
    AuthMiddleware,
    Gate,
    Guard,
    Policy,
    current_user_or_none,
)
from pylar.foundation import (
    AppConfig,
    Application,
    Container,
    ServiceProvider,
)
from pylar.http import (
    HttpKernel,
    Request,
    Response,
    Unauthorized,
    json,
)
from pylar.routing import Router

# --------------------------------------------------------------------- domain


@dataclass(frozen=True)
class AuthUser:
    id: int
    is_admin: bool

    @property
    def auth_identifier(self) -> int:
        return self.id

    @property
    def auth_password_hash(self) -> str:
        return ""


@dataclass(frozen=True)
class Document:
    id: int
    owner_id: int


_USERS = {
    1: AuthUser(id=1, is_admin=False),  # owner of doc 42
    2: AuthUser(id=2, is_admin=True),   # admin
    3: AuthUser(id=3, is_admin=False),  # outsider
}

_DOCUMENT = Document(id=42, owner_id=1)


class DocumentPolicy(Policy[Document]):
    async def update(self, user: AuthUser, instance: Document) -> bool:  # type: ignore[override]
        return user.is_admin or user.id == instance.owner_id


# ----------------------------------------------------------------- guard impl


class HeaderGuard:
    """Resolves users via the ``X-User-Id`` header. Test-only stand-in."""

    async def authenticate(self, request: Request) -> AuthUser | None:
        raw = request.headers.get("x-user-id")
        if raw is None:
            return None
        try:
            return _USERS.get(int(raw))
        except ValueError:
            return None


# ---------------------------------------------------------------- controllers


class DocumentController:
    def __init__(self, gate: Gate) -> None:
        self.gate = gate

    async def update(self, request: Request) -> Response:
        user = current_user_or_none()
        if user is None:
            raise Unauthorized()
        await self.gate.authorize(user, "update", _DOCUMENT)
        return json({"ok": True, "user_id": user.auth_identifier})


# ------------------------------------------------------------------- providers


class _AuthSetupProvider(ServiceProvider):
    def register(self, container: Container) -> None:
        container.singleton(Guard, HeaderGuard)  # type: ignore[type-abstract]
        gate = Gate()
        gate.policy(Document, DocumentPolicy())
        container.singleton(Gate, lambda: gate)


class _RouteProvider(ServiceProvider):
    def register(self, container: Container) -> None:
        router = Router()
        router.put(
            "/documents/{document_id:int}",
            DocumentController.update,
            middleware=[AuthMiddleware],
        )
        container.singleton(Router, lambda: router)


@pytest.fixture
async def client() -> httpx.AsyncClient:
    app = Application(
        base_path=Path("/tmp/pylar-auth-test"),
        config=AppConfig(
            name="auth-test",
            debug=True,
            providers=(_AuthSetupProvider, _RouteProvider),
        ),
    )
    await app.bootstrap()
    transport = httpx.ASGITransport(app=HttpKernel(app).asgi())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await app.shutdown()


# ------------------------------------------------------------------------ tests


async def test_owner_is_authorized(client: httpx.AsyncClient) -> None:
    response = await client.put("/documents/42", headers={"x-user-id": "1"})
    assert response.status_code == 200
    assert response.json() == {"ok": True, "user_id": 1}


async def test_admin_is_authorized(client: httpx.AsyncClient) -> None:
    response = await client.put("/documents/42", headers={"x-user-id": "2"})
    assert response.status_code == 200
    assert response.json() == {"ok": True, "user_id": 2}


async def test_outsider_is_forbidden_with_403(client: httpx.AsyncClient) -> None:
    response = await client.put("/documents/42", headers={"x-user-id": "3"})
    assert response.status_code == 403
    payload = response.json()
    assert payload["ability"] == "update"
    assert "update" in payload["error"]


async def test_anonymous_request_is_unauthorized(client: httpx.AsyncClient) -> None:
    response = await client.put("/documents/42")
    assert response.status_code == 401
