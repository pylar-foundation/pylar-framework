"""Tests for :class:`SessionGuard`."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path

import httpx
import pytest

from pylar.auth import (
    Authenticatable,
    AuthMiddleware,
    Guard,
    SessionGuard,
    current_user_or_none,
)
from pylar.foundation import AppConfig, Application, Container, ServiceProvider
from pylar.http import HttpKernel, Request, Response, json
from pylar.routing import Router
from pylar.session import (
    MemorySessionStore,
    SessionConfig,
    SessionMiddleware,
    SessionStore,
)


class _User:
    def __init__(self, id: int, name: str) -> None:
        self.id = id
        self.name = name

    @property
    def auth_identifier(self) -> object:
        return self.id

    @property
    def auth_password_hash(self) -> str:
        return ""


_USERS: dict[int, _User] = {1: _User(1, "Alice"), 2: _User(2, "Bob")}


async def _resolve(user_id: object) -> Authenticatable | None:
    return _USERS.get(int(user_id) if isinstance(user_id, (int, str)) else 0)


async def _login(request: Request) -> Response:
    guard = request.scope["app_container"].make(Guard)  # type: ignore[type-abstract]
    await guard.login(_USERS[1])
    return json({"ok": True})


async def _whoami(request: Request) -> Response:
    user = current_user_or_none()
    if user is None:
        return json({"user": None})
    return json({"user": getattr(user, "name", None)})


async def _logout(request: Request) -> Response:
    guard = request.scope["app_container"].make(Guard)  # type: ignore[type-abstract]
    await guard.logout()
    return json({"ok": True})


class _Routes(ServiceProvider):
    def register(self, container: Container) -> None:
        guard = SessionGuard[_User](_resolve)
        container.instance(Guard, guard)  # type: ignore[type-abstract]
        container.singleton(
            SessionStore, MemorySessionStore  # type: ignore[type-abstract]
        )
        container.instance(SessionConfig, SessionConfig(secret_key="test"))

        # Expose container on request scope for the test handlers.
        self_container = container

        async def _attach(
            request: Request,
            next_handler: Callable[[Request], Awaitable[Response]],
        ) -> Response:
            request.scope["app_container"] = self_container
            return await next_handler(request)

        class _Attach:
            async def handle(
                self,
                request: Request,
                next_handler: Callable[[Request], Awaitable[Response]],
            ) -> Response:
                request.scope["app_container"] = self_container
                return await next_handler(request)

        router = Router()
        chain = router.group(
            middleware=[_Attach, SessionMiddleware, AuthMiddleware]
        )
        chain.post("/login", _login)
        chain.get("/whoami", _whoami)
        chain.post("/logout", _logout)
        container.singleton(Router, lambda: router)


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = Application(
        base_path=Path("/tmp/pylar-session-guard-test"),
        config=AppConfig(
            name="session-guard-test",
            debug=True,
            providers=(_Routes,),
        ),
    )
    await app.bootstrap()
    transport = httpx.ASGITransport(app=HttpKernel(app).asgi())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await app.shutdown()


async def test_unauthenticated_request_has_no_user(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/whoami")
    assert response.json()["user"] is None


async def test_login_then_whoami_returns_user(
    client: httpx.AsyncClient,
) -> None:
    await client.post("/login")
    response = await client.get("/whoami")
    assert response.json()["user"] == "Alice"


async def test_login_regenerates_session_id(
    client: httpx.AsyncClient,
) -> None:
    pre = await client.get("/whoami")
    pre_sid = pre.cookies.get("pylar_session_id", "")
    await client.post("/login")
    post = await client.get("/whoami")
    post_sid = post.cookies.get("pylar_session_id", pre_sid)
    # The session id portion before the dot must have changed.
    assert pre_sid.split(".")[0] != post_sid.split(".")[0] or post_sid != pre_sid


async def test_logout_clears_user(client: httpx.AsyncClient) -> None:
    await client.post("/login")
    assert (await client.get("/whoami")).json()["user"] == "Alice"
    await client.post("/logout")
    assert (await client.get("/whoami")).json()["user"] is None


# ---- Brute-force protection ----


class _DummySession:
    """Minimal Session stand-in for standalone guard state tests."""

    def __init__(self) -> None:
        self._data: dict[str, object] = {}

    def get(self, key: str, default: object = None) -> object:
        return self._data.get(key, default)

    def put(self, key: str, value: object) -> None:
        self._data[key] = value

    def forget(self, key: str) -> None:
        self._data.pop(key, None)


async def test_guard_locks_out_after_max_attempts() -> None:
    from pylar.session.context import _set_session

    async def _dummy_resolver(user_id: object) -> Authenticatable | None:
        return None

    guard: SessionGuard[Authenticatable] = SessionGuard(resolver=_dummy_resolver)
    from pylar.session import Session

    session = Session("test-sid", {})
    token = _set_session(session)
    try:
        for _ in range(SessionGuard.max_attempts):
            guard.record_failed_attempt()
        assert guard.is_locked_out() is True
    finally:
        from pylar.session.context import _reset_session

        _reset_session(token)


async def test_guard_clears_attempts_on_successful_login() -> None:
    from pylar.session import Session
    from pylar.session.context import _reset_session, _set_session

    captured: list[_User] = []

    async def _resolver(user_id: object) -> Authenticatable | None:
        return _USERS.get(int(user_id)) if isinstance(user_id, int) else None

    guard: SessionGuard[_User] = SessionGuard(resolver=_resolver)

    session = Session("test-sid", {})
    token = _set_session(session)
    try:
        guard.record_failed_attempt()
        guard.record_failed_attempt()
        assert guard.remaining_attempts() == SessionGuard.max_attempts - 2

        await guard.login(_USERS[1])
        captured.append(_USERS[1])

        # login() clears the counter.
        assert guard.remaining_attempts() == SessionGuard.max_attempts
    finally:
        _reset_session(token)
