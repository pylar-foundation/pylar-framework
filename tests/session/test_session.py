"""Tests for the session layer (store, middleware, SessionGuard)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from pylar.foundation import AppConfig, Application, Container, ServiceProvider
from pylar.http import HttpKernel, Request, Response, json
from pylar.routing import Router
from pylar.session import (
    FileSessionStore,
    MemorySessionStore,
    Session,
    SessionConfig,
    SessionMiddleware,
    SessionStore,
    current_session,
)

# ----------------------------------------------------------- raw stores


async def test_memory_store_round_trip() -> None:
    store = MemorySessionStore()
    await store.write("sid", {"k": "v"}, ttl_seconds=60)
    assert await store.read("sid") == {"k": "v"}
    await store.destroy("sid")
    assert await store.read("sid") is None


async def test_memory_store_expires() -> None:
    store = MemorySessionStore()
    await store.write("sid", {"k": 1}, ttl_seconds=0)
    await asyncio.sleep(0.01)
    assert await store.read("sid") is None


async def test_file_store_round_trip(tmp_path: Path) -> None:
    store = FileSessionStore(tmp_path / "sessions")
    await store.write("sid", {"k": "v"}, ttl_seconds=60)
    assert await store.read("sid") == {"k": "v"}
    await store.destroy("sid")
    assert await store.read("sid") is None


async def test_file_store_handles_unsafe_ids(tmp_path: Path) -> None:
    store = FileSessionStore(tmp_path / "sessions")
    await store.write("../../etc/passwd", {"x": 1}, ttl_seconds=60)
    assert await store.read("../../etc/passwd") == {"x": 1}


@dataclass(frozen=True)
class _Snapshot:
    id: int
    ts: datetime


async def test_file_store_preserves_python_objects(tmp_path: Path) -> None:
    """Pickle lets the session carry datetime, dataclass, frozenset, etc."""
    store = FileSessionStore(tmp_path / "sessions")
    now = datetime.now(UTC)
    await store.write(
        "obj",
        {"snap": _Snapshot(1, now), "tags": frozenset({"a", "b"})},
        ttl_seconds=60,
    )
    data = await store.read("obj")
    assert data is not None
    assert data["snap"] == _Snapshot(1, now)
    assert isinstance(data["tags"], frozenset)


async def test_memory_store_preserves_python_objects() -> None:
    store = MemorySessionStore()
    now = datetime.now(UTC)
    await store.write("obj", {"snap": _Snapshot(2, now)}, ttl_seconds=60)
    data = await store.read("obj")
    assert data is not None
    assert data["snap"].ts == now


# ------------------------------------------------------------ Session


def test_session_get_returns_default_for_missing_key() -> None:
    s = Session("sid", {})
    assert s.get("missing", "fallback") == "fallback"


def test_session_put_marks_dirty() -> None:
    s = Session("sid", {})
    assert s.is_dirty is False
    s.put("k", 1)
    assert s.is_dirty is True
    assert s.get("k") == 1


def test_session_flash_visible_only_until_payload_rotates() -> None:
    s = Session("sid", {})
    s.flash("msg", "hi")
    payload = s.to_payload()
    # Next request — pretend the store handed back the persisted payload.
    s2 = Session("sid", payload)
    assert s2.get("msg") == "hi"
    # Third request — the flash slot is gone.
    s3 = Session("sid", s2.to_payload())
    assert s3.get("msg") is None


def test_session_regenerate_keeps_data_changes_id() -> None:
    s = Session("old-id", {"k": 1})
    s.regenerate()
    assert s.regenerated_from == "old-id"
    assert s.id != "old-id"
    assert s.get("k") == 1


def test_session_destroy_clears_payload() -> None:
    s = Session("sid", {"k": 1})
    s.destroy()
    assert s.is_destroyed is True
    assert s.get("k") is None


# ------------------------------------------------ end-to-end via middleware


async def _read_sid(request: Request) -> Response:
    s = current_session()
    return json({"sid": s.id, "value": s.get("counter", 0)})


async def _bump(request: Request) -> Response:
    s = current_session()
    s.put("counter", s.get("counter", 0) + 1)
    return json({"counter": s.get("counter")})


async def _flash(request: Request) -> Response:
    s = current_session()
    s.flash("msg", "hello")
    return json({"flashed": True})


async def _read_flash(request: Request) -> Response:
    s = current_session()
    return json({"msg": s.get("msg")})


async def _logout(request: Request) -> Response:
    s = current_session()
    s.destroy()
    return json({"out": True})


class _Routes(ServiceProvider):
    def register(self, container: Container) -> None:
        router = Router()
        group = router.group(middleware=[SessionMiddleware])
        group.get("/sid", _read_sid)
        group.post("/bump", _bump)
        group.post("/flash", _flash)
        group.get("/flash", _read_flash)
        group.post("/logout", _logout)
        container.singleton(Router, lambda: router)

        # Bind the session middleware deps via the container.
        container.singleton(
            SessionStore,  # type: ignore[type-abstract]
            MemorySessionStore,
        )
        container.instance(
            SessionConfig,
            SessionConfig(secret_key="test-secret"),
        )


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = Application(
        base_path=Path("/tmp/pylar-session-test"),
        config=AppConfig(
            name="session-test",
            debug=True,
            providers=(_Routes,),
        ),
    )
    await app.bootstrap()
    transport = httpx.ASGITransport(app=HttpKernel(app).asgi())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await app.shutdown()


async def test_first_request_sets_signed_cookie(client: httpx.AsyncClient) -> None:
    response = await client.get("/sid")
    assert response.status_code == 200
    assert "pylar_session_id" in response.cookies
    raw = response.cookies["pylar_session_id"]
    sid, _, sig = raw.rpartition(".")
    assert sid and sig


async def test_session_data_persists_across_requests(
    client: httpx.AsyncClient,
) -> None:
    r1 = await client.post("/bump")
    assert r1.json()["counter"] == 1
    r2 = await client.post("/bump")
    assert r2.json()["counter"] == 2


async def test_tampered_cookie_falls_back_to_fresh_session(
    client: httpx.AsyncClient,
) -> None:
    await client.post("/bump")
    # Forge a bogus signature.
    client.cookies.set("pylar_session_id", "evil-sid.bogussig")
    r = await client.post("/bump")
    assert r.json()["counter"] == 1  # fresh session, not 3


async def test_flash_visible_on_next_request_only(
    client: httpx.AsyncClient,
) -> None:
    await client.post("/flash")
    r1 = await client.get("/flash")
    assert r1.json()["msg"] == "hello"
    r2 = await client.get("/flash")
    assert r2.json()["msg"] is None


async def test_logout_destroys_session(client: httpx.AsyncClient) -> None:
    await client.post("/bump")  # counter = 1
    await client.post("/logout")
    r = await client.post("/bump")
    assert r.json()["counter"] == 1  # fresh session


# ---- cookie_secure auto-upgrade in provider ----


async def _cookie_secure_via_provider(debug: bool) -> bool:
    """Build SessionMiddleware via provider and return its resolved cookie_secure."""
    from pylar.foundation import AppConfig, Application
    from pylar.session.provider import SessionServiceProvider
    from pylar.session.stores.memory import MemorySessionStore

    config = AppConfig(
        name="test",
        debug=debug,
        providers=(SessionServiceProvider,),
    )
    app = Application(
        config=config,
        base_path=Path("/tmp/pylar-session-cookie-test"),
    )
    await app.bootstrap()
    app.container.instance(
        SessionConfig,
        SessionConfig(secret_key="a" * 32, cookie_secure=False),
    )
    app.container.instance(SessionStore, MemorySessionStore())
    middleware = app.container.make(SessionMiddleware)
    return middleware._config.cookie_secure


async def test_session_provider_upgrades_cookie_secure_in_production() -> None:
    """SessionServiceProvider forces cookie_secure=True when debug=False."""
    assert await _cookie_secure_via_provider(debug=False) is True


async def test_session_provider_keeps_explicit_cookie_secure_in_debug() -> None:
    """Debug mode leaves cookie_secure untouched (tests/dev often use HTTP)."""
    assert await _cookie_secure_via_provider(debug=True) is False
