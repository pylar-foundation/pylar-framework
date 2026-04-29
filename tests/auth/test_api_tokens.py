"""Tests for Sanctum-style API tokens (ADR-0009 phase 11b).

Uses the ``manager`` / ``session`` fixtures from the framework's
conftest. The user fixture is a minimal Authenticatable row so the
tokenable lookup has something to bind against.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest

from pylar.auth import TokenMiddleware, create_api_token, hash_token
from pylar.auth.context import current_user_or_none
from pylar.database import (
    ConnectionManager,
    DatabaseConfig,
    Model,
    fields,
    transaction,
)
from pylar.database.session import use_session


class _TokenableUser(Model, metaclass=type(Model)):  # type: ignore[misc]
    """Minimal Authenticatable for token tests — only the fields the
    token lookup actually reads."""

    class Meta:
        db_table = "tokenable_users"

    name = fields.CharField(max_length=100)

    @property
    def auth_identifier(self) -> object:
        return self.id

    @property
    def auth_password_hash(self) -> str:
        return ""


@pytest.fixture
async def manager() -> AsyncIterator[ConnectionManager]:
    mgr = ConnectionManager(DatabaseConfig(url="sqlite+aiosqlite:///:memory:"))
    await mgr.initialize()
    async with mgr.engine.begin() as conn:
        await conn.run_sync(Model.metadata.create_all)
    try:
        yield mgr
    finally:
        await mgr.dispose()


async def _make_user(manager: ConnectionManager) -> int:
    async with use_session(manager):
        async with transaction():
            user = _TokenableUser(name="Alice")
            await _TokenableUser.query.save(user)
            return user.id


# ------------------------------------------------------- minting


async def test_create_api_token_returns_plaintext_and_row(
    manager: ConnectionManager,
) -> None:
    user_id = await _make_user(manager)

    async with use_session(manager):
        async with transaction():
            user = await _TokenableUser.query.get(user_id)
            plaintext, token = await create_api_token(
                user, name="Mobile app", abilities=["posts.*"],
            )

    assert plaintext.startswith("pylat_")
    assert token.token_hash == hash_token(plaintext)
    assert json.loads(token.abilities) == ["posts.*"]


async def test_token_ability_wildcards_and_prefix_matching(
    manager: ConnectionManager,
) -> None:
    user_id = await _make_user(manager)

    async with use_session(manager):
        async with transaction():
            user = await _TokenableUser.query.get(user_id)
            _, scoped = await create_api_token(
                user, name="Scoped", abilities=["posts.*", "comments.read"],
            )
            _, star = await create_api_token(
                user, name="Admin", abilities=["*"],
            )
            _, empty = await create_api_token(
                user, name="Full",
            )

    assert scoped.can("posts.edit")
    assert scoped.can("posts.delete")
    assert scoped.can("comments.read")
    assert not scoped.can("comments.edit")
    assert not scoped.can("users.manage")

    assert star.can("anything.at.all")
    # Empty abilities = all abilities, same as star.
    assert empty.can("anything.at.all")


async def test_expires_in_builds_future_expiry(
    manager: ConnectionManager,
) -> None:
    user_id = await _make_user(manager)

    async with use_session(manager):
        async with transaction():
            user = await _TokenableUser.query.get(user_id)
            _, token = await create_api_token(
                user, name="timed", expires_in=timedelta(minutes=10),
            )
    assert not token.is_expired()
    past = datetime.now(UTC) + timedelta(hours=1)
    assert token.is_expired(now=past)


async def test_expires_at_and_expires_in_conflict_raises(
    manager: ConnectionManager,
) -> None:
    user_id = await _make_user(manager)

    async with use_session(manager):
        async with transaction():
            user = await _TokenableUser.query.get(user_id)
            with pytest.raises(ValueError):
                await create_api_token(
                    user,
                    name="conflict",
                    expires_at=datetime.now(UTC),
                    expires_in=timedelta(hours=1),
                )


# ------------------------------------------------------- middleware


class _StubRequest:
    """Minimal request shim for TokenMiddleware — the middleware only
    reads headers + scope."""

    def __init__(self, headers: dict[str, str]) -> None:
        self.headers = {k.lower(): v for k, v in headers.items()}
        self.scope: dict[str, object] = {}


async def test_middleware_lets_request_through_without_bearer_header() -> None:
    seen: list[object] = []

    async def next_handler(req: object) -> str:
        seen.append(req)
        return "ok"

    req = _StubRequest({})
    result = await TokenMiddleware().handle(req, next_handler)
    assert result == "ok"
    assert seen == [req]
    assert current_user_or_none() is None


async def test_middleware_rejects_unknown_bearer_token(
    manager: ConnectionManager,
) -> None:
    async with use_session(manager):
        req = _StubRequest({"Authorization": "Bearer unknown_plaintext_token"})
        response = await TokenMiddleware().handle(req, _boom)
    assert response.status_code == 401
    body = json.loads(response.body.decode())
    assert body["error"]["code"] == "unauthenticated"


async def test_middleware_pins_user_on_valid_bearer(
    manager: ConnectionManager,
) -> None:
    user_id = await _make_user(manager)

    async with use_session(manager):
        async with transaction():
            user = await _TokenableUser.query.get(user_id)
            plaintext, _ = await create_api_token(user, name="phone")

    captured: list[object] = []

    async def handler(req: object) -> str:
        captured.append(current_user_or_none())
        return "ok"

    async with use_session(manager):
        req = _StubRequest({"Authorization": f"Bearer {plaintext}"})
        result = await TokenMiddleware().handle(req, handler)

    assert result == "ok"
    pinned = captured[0]
    assert pinned is not None
    assert pinned.id == user_id


async def test_middleware_rejects_expired_token(
    manager: ConnectionManager,
) -> None:
    user_id = await _make_user(manager)

    async with use_session(manager):
        async with transaction():
            user = await _TokenableUser.query.get(user_id)
            plaintext, _token = await create_api_token(
                user, name="old", expires_in=timedelta(seconds=-1),
            )

    async with use_session(manager):
        req = _StubRequest({"Authorization": f"Bearer {plaintext}"})
        response = await TokenMiddleware().handle(req, _boom)

    assert response.status_code == 401


async def test_required_ability_blocks_missing_scope(
    manager: ConnectionManager,
) -> None:
    user_id = await _make_user(manager)

    async with use_session(manager):
        async with transaction():
            user = await _TokenableUser.query.get(user_id)
            plaintext, _ = await create_api_token(
                user, name="scoped", abilities=["posts.read"],
            )

    class Edit(TokenMiddleware):
        required_ability = "posts.edit"

    async with use_session(manager):
        req = _StubRequest({"Authorization": f"Bearer {plaintext}"})
        response = await Edit().handle(req, _boom)

    assert response.status_code == 401
    body = json.loads(response.body.decode())
    assert "ability" in body["error"]["message"]


async def _boom(req: object) -> object:
    raise AssertionError("next_handler should not have been called")
