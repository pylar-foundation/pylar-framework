"""Tests for email verification + password reset (ADR-0009 phase 11c)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qsl, urlparse

import pytest

from pylar.auth import (
    ExpiredSignature,
    InvalidSignature,
    MissingSignature,
    RequireVerifiedEmailMiddleware,
    UrlSigner,
    build_password_reset_url,
    build_verification_url,
    mark_email_verified,
    reset_password,
    verify_from_request,
)
from pylar.auth.context import authenticate_as
from pylar.auth.hashing import Pbkdf2PasswordHasher
from pylar.auth.verification import to_response
from pylar.database import (
    ConnectionManager,
    DatabaseConfig,
    Model,
    fields,
    transaction,
)
from pylar.database.session import use_session


class _VerifyUser(Model, metaclass=type(Model)):  # type: ignore[misc]
    class Meta:
        db_table = "verify_users"

    name = fields.CharField(max_length=100)
    password_hash = fields.CharField(max_length=255, default="")
    email_verified_at = fields.DateTimeField(null=True)

    @property
    def auth_identifier(self) -> object:
        return self.id

    @property
    def auth_password_hash(self) -> str:
        return self.password_hash  # type: ignore[return-value]


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
            user = _VerifyUser(name="Alice")
            await _VerifyUser.query.save(user)
            return user.id


def _qs(url: str) -> dict[str, str]:
    return dict(parse_qsl(urlparse(url).query, keep_blank_values=True))


# ------------------------------------------------------- build URLs


async def test_verification_url_carries_user_id_and_expiry(
    manager: ConnectionManager,
) -> None:
    signer = UrlSigner("k")
    user_id = await _make_user(manager)
    async with use_session(manager):
        user = await _VerifyUser.query.get(user_id)

    url = build_verification_url(user, signer)
    q = _qs(url)
    assert q["user_id"] == str(user_id)
    assert "expires" in q
    assert "signature" in q


async def test_verification_url_folds_extra_params_under_signature(
    manager: ConnectionManager,
) -> None:
    signer = UrlSigner("k")
    user_id = await _make_user(manager)
    async with use_session(manager):
        user = await _VerifyUser.query.get(user_id)

    url = build_verification_url(
        user, signer, extra_params={"redirect": "/dashboard"},
    )
    q = _qs(url)
    assert q["redirect"] == "/dashboard"
    # Tampering with the redirect invalidates the signature.
    q["redirect"] = "/attacker"
    with pytest.raises(InvalidSignature):
        signer.verify("/auth/verify", q)


# ------------------------------------------------------- verify + mark


async def test_mark_email_verified_stamps_timestamp_once(
    manager: ConnectionManager,
) -> None:
    user_id = await _make_user(manager)

    async with use_session(manager):
        async with transaction():
            user = await _VerifyUser.query.get(user_id)
            assert user.email_verified_at is None
            await mark_email_verified(user)

    async with use_session(manager):
        user = await _VerifyUser.query.get(user_id)
        first_stamp = user.email_verified_at
        assert first_stamp is not None

    # Second call is a no-op — the timestamp doesn't move.
    async with use_session(manager):
        async with transaction():
            reloaded = await _VerifyUser.query.get(user_id)
            await mark_email_verified(reloaded)

    async with use_session(manager):
        user = await _VerifyUser.query.get(user_id)
        assert user.email_verified_at == first_stamp


async def test_verify_from_request_rejects_expired_link(
    manager: ConnectionManager,
) -> None:
    signer = UrlSigner("k")
    user_id = await _make_user(manager)
    async with use_session(manager):
        user = await _VerifyUser.query.get(user_id)

    url = build_verification_url(
        user, signer, expires_in=timedelta(seconds=-1),
    )
    q = _qs(url)

    class _Req:
        @property
        def query_params(self) -> dict[str, str]:
            return q

    with pytest.raises(ExpiredSignature):
        verify_from_request(_Req(), signer, path="/auth/verify")  # type: ignore[arg-type]


async def test_to_response_maps_exceptions_to_envelopes() -> None:
    import json

    resp = to_response(ExpiredSignature("expired"))
    assert resp.status_code == 410
    assert json.loads(resp.body.decode())["error"]["code"] == "link_expired"

    resp = to_response(InvalidSignature("bad"))
    assert resp.status_code == 400
    assert json.loads(resp.body.decode())["error"]["code"] == "link_invalid"

    resp = to_response(MissingSignature("none"))
    assert resp.status_code == 400
    assert json.loads(resp.body.decode())["error"]["code"] == "link_invalid"


# ------------------------------------------------------- password reset


async def test_password_reset_url_uses_reset_path_and_short_ttl(
    manager: ConnectionManager,
) -> None:
    signer = UrlSigner("k")
    user_id = await _make_user(manager)
    async with use_session(manager):
        user = await _VerifyUser.query.get(user_id)

    url = build_password_reset_url(user, signer)
    parsed = urlparse(url)
    assert parsed.path == "/auth/password/reset"

    q = _qs(url)
    # Reset default TTL is 1 hour; well under the 24 h verification TTL.
    assert int(q["expires"]) - int(datetime.now(UTC).timestamp()) < 3700


async def test_reset_password_rehashes_and_persists(
    manager: ConnectionManager,
) -> None:
    user_id = await _make_user(manager)
    hasher = Pbkdf2PasswordHasher()

    async with use_session(manager):
        async with transaction():
            user = await _VerifyUser.query.get(user_id)
            await reset_password(user, new_password="n3w-P4ss", hasher=hasher)

    async with use_session(manager):
        user = await _VerifyUser.query.get(user_id)
        stored = user.password_hash
        assert stored
        assert hasher.verify("n3w-P4ss", stored)


# --------------------------------------------------- require-verified guard


async def test_middleware_403s_unverified_user(manager: ConnectionManager) -> None:
    import json

    user_id = await _make_user(manager)
    async with use_session(manager):
        user = await _VerifyUser.query.get(user_id)

    async def never_called(req: object) -> object:
        raise AssertionError("next_handler must not run for unverified user")

    class _Req:
        pass

    with authenticate_as(user):
        resp = await RequireVerifiedEmailMiddleware().handle(
            _Req(), never_called,  # type: ignore[arg-type]
        )

    assert resp.status_code == 403
    assert json.loads(resp.body.decode())["error"]["code"] == "email_unverified"


async def test_middleware_passes_through_verified_user(
    manager: ConnectionManager,
) -> None:
    user_id = await _make_user(manager)

    async with use_session(manager):
        async with transaction():
            user = await _VerifyUser.query.get(user_id)
            await mark_email_verified(user)

    async def ok(req: object) -> str:
        return "pass"

    class _Req:
        pass

    async with use_session(manager):
        user = await _VerifyUser.query.get(user_id)
        with authenticate_as(user):
            result = await RequireVerifiedEmailMiddleware().handle(
                _Req(), ok,  # type: ignore[arg-type]
            )

    assert result == "pass"


async def test_middleware_401s_anonymous_request() -> None:
    import json

    async def never_called(req: object) -> object:
        raise AssertionError

    class _Req:
        pass

    resp = await RequireVerifiedEmailMiddleware().handle(
        _Req(), never_called,  # type: ignore[arg-type]
    )
    assert resp.status_code == 401
    assert json.loads(resp.body.decode())["error"]["code"] == "unauthenticated"
