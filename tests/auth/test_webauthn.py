"""Tests for WebAuthn ceremonies (ADR-0013 phase 15a).

The real crypto in ``py_webauthn`` is exercised by its own test
suite. What this module pins down is the *framework* plumbing:

* challenges round-trip through the ambient :class:`Session`
* the correct ceremony label is enforced on verification
* the credential row is persisted on success, cleared on failure
* ``verify_authentication`` finds the row by id, updates the sign
  count, and stamps the session
* TTL expiry and cross-ceremony mismatches raise
  :class:`WebauthnChallengeExpiredError` not the generic error

The ``py_webauthn`` verify helpers are monkeypatched with a stub so
the tests don't have to mint a real authenticator signature every
time; the stub returns a dataclass shaped like the library's
``VerifiedRegistration`` / ``VerifiedAuthentication`` types.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from pylar.auth.webauthn import (
    WebauthnChallengeExpiredError,
    WebauthnConfig,
    WebauthnCredential,
    WebauthnCredentialNotFoundError,
    WebauthnServer,
    WebauthnVerificationError,
)
from pylar.auth.webauthn import server as server_module
from pylar.database import (
    ConnectionManager,
    DatabaseConfig,
    Model,
    fields,
    transaction,
)
from pylar.database.session import use_session
from pylar.session.context import _reset_session, _set_session
from pylar.session.session import Session


class _WebauthnUser(Model, metaclass=type(Model)):  # type: ignore[misc]
    """Minimal Authenticatable — enough for the tokenable lookup."""

    class Meta:
        db_table = "webauthn_users"

    email = fields.CharField(max_length=100)
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


@pytest.fixture
def session() -> Iterator[Session]:
    """Bind a Session into the contextvar for the duration of the test."""
    s = Session(session_id="test-session", data={})
    token = _set_session(s)
    try:
        yield s
    finally:
        _reset_session(token)


@pytest.fixture
def server() -> WebauthnServer:
    return WebauthnServer(
        WebauthnConfig(rp_id="localhost", rp_name="Test RP"),
    )


async def _make_user(manager: ConnectionManager) -> int:
    async with use_session(manager):
        async with transaction():
            user = _WebauthnUser(
                email="alice@example.com", name="Alice",
            )
            await _WebauthnUser.query.save(user)
            return int(user.id)


async def _load_user(manager: ConnectionManager, user_id: int) -> _WebauthnUser:
    async with use_session(manager):
        user = await _WebauthnUser.query.get(user_id)
        assert user is not None
        return user


# --------------------------------------------------- stubs


@dataclass
class _FakeVerifiedRegistration:
    credential_id: bytes
    credential_public_key: bytes
    sign_count: int
    aaguid: str | None
    credential_device_type: str
    credential_backed_up: bool


@dataclass
class _FakeVerifiedAuthentication:
    credential_id: bytes
    new_sign_count: int
    credential_device_type: str
    credential_backed_up: bool
    user_verified: bool


def _patch_registration(
    monkeypatch: pytest.MonkeyPatch,
    *,
    credential_id: bytes = b"cred-0001",
    public_key: bytes = b"public-key-bytes",
    sign_count: int = 0,
    raises: Exception | None = None,
) -> None:
    def _fake(*, credential: Any, **kwargs: Any) -> _FakeVerifiedRegistration:
        if raises is not None:
            raise raises
        return _FakeVerifiedRegistration(
            credential_id=credential_id,
            credential_public_key=public_key,
            sign_count=sign_count,
            aaguid="00000000-0000-0000-0000-000000000000",
            credential_device_type="multi_device",
            credential_backed_up=True,
        )

    monkeypatch.setattr(
        server_module, "verify_registration_response", _fake,
    )


def _patch_authentication(
    monkeypatch: pytest.MonkeyPatch,
    *,
    new_sign_count: int = 1,
    raises: Exception | None = None,
) -> None:
    def _fake(*, credential: Any, **kwargs: Any) -> _FakeVerifiedAuthentication:
        if raises is not None:
            raise raises
        cred_id = (
            credential.get("id")
            if isinstance(credential, dict)
            else b""
        )
        return _FakeVerifiedAuthentication(
            credential_id=cred_id.encode() if isinstance(cred_id, str) else cred_id,
            new_sign_count=new_sign_count,
            credential_device_type="multi_device",
            credential_backed_up=True,
            user_verified=True,
        )

    monkeypatch.setattr(
        server_module, "verify_authentication_response", _fake,
    )


# --------------------------------------------------- tests


async def test_registration_options_expose_rp_and_store_challenge(
    manager: ConnectionManager, server: WebauthnServer, session: Session,
) -> None:
    user_id = await _make_user(manager)
    async with use_session(manager):
        user = await _load_user(manager, user_id)
        options = await server.make_registration_options(user)

    assert options["rp"]["id"] == "localhost"
    assert options["rp"]["name"] == "Test RP"
    assert options["user"]["name"] == "alice@example.com"
    assert "challenge" in options
    # Challenge stashed on session under the module-private key.
    stored = session.get("_webauthn.challenge")
    assert isinstance(stored, dict)
    assert stored["ceremony"] == "registration"


async def test_register_persists_credential_and_clears_challenge(
    manager: ConnectionManager,
    server: WebauthnServer,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = await _make_user(manager)
    _patch_registration(monkeypatch, credential_id=b"cred-A")

    async with use_session(manager):
        user = await _load_user(manager, user_id)
        await server.make_registration_options(user)
        async with transaction():
            cred = await server.verify_registration(
                user,
                {
                    "id": "AA",
                    "rawId": "AA",
                    "response": {"transports": ["internal", "hybrid"]},
                    "type": "public-key",
                },
                nickname="Laptop passkey",
            )

    assert cred.credential_id == b"cred-A"
    assert cred.nickname == "Laptop passkey"
    assert cred.transport_list == ["internal", "hybrid"]
    assert cred.backup_eligible is True
    # Challenge cleared after successful verify.
    assert session.get("_webauthn.challenge") is None


async def test_register_failure_clears_challenge_and_raises(
    manager: ConnectionManager,
    server: WebauthnServer,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = await _make_user(manager)
    _patch_registration(
        monkeypatch, raises=ValueError("bad signature"),
    )

    async with use_session(manager):
        user = await _load_user(manager, user_id)
        await server.make_registration_options(user)
        with pytest.raises(WebauthnVerificationError):
            await server.verify_registration(user, {"id": "AA"})
    assert session.get("_webauthn.challenge") is None


async def test_authentication_options_discoverable_omit_allow_credentials(
    server: WebauthnServer, session: Session,
) -> None:
    options = await server.make_authentication_options()
    assert options["rpId"] == "localhost"
    # No user = discoverable (passwordless-primary) flow.
    assert options.get("allowCredentials") in (None, [])
    stored = session.get("_webauthn.challenge")
    assert isinstance(stored, dict)
    assert stored["ceremony"] == "authentication"


async def test_authentication_options_with_user_lists_their_credentials(
    manager: ConnectionManager,
    server: WebauthnServer,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = await _make_user(manager)
    _patch_registration(monkeypatch, credential_id=b"cred-B")

    async with use_session(manager):
        user = await _load_user(manager, user_id)
        await server.make_registration_options(user)
        async with transaction():
            await server.verify_registration(
                user, {"id": "BB", "response": {"transports": ["usb"]}},
            )

        options = await server.make_authentication_options(user)

    assert isinstance(options["allowCredentials"], list)
    assert len(options["allowCredentials"]) == 1
    # py_webauthn encodes the bytes as base64url in JSON; we don't
    # pin the exact encoding, just that the descriptor exists.


async def test_verify_authentication_returns_user_and_updates_row(
    manager: ConnectionManager,
    server: WebauthnServer,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = await _make_user(manager)
    _patch_registration(monkeypatch, credential_id=b"cred-C")
    _patch_authentication(monkeypatch, new_sign_count=42)

    async with use_session(manager):
        user = await _load_user(manager, user_id)
        await server.make_registration_options(user)
        async with transaction():
            await server.verify_registration(
                user, {"id": "CC", "response": {"transports": []}},
            )

        await server.make_authentication_options()
        # The browser's assertion response carries base64url(id).
        # We feed raw bytes here; verify_authentication decodes the
        # `id` field via base64url_to_bytes. Encode to match.
        from webauthn.helpers.bytes_to_base64url import bytes_to_base64url
        cred_id_b64 = bytes_to_base64url(b"cred-C")
        async with transaction():
            resolved_user, resolved_cred = await server.verify_authentication(
                {"id": cred_id_b64, "rawId": cred_id_b64, "type": "public-key"},
            )

    assert int(resolved_user.auth_identifier) == user_id
    assert resolved_cred.sign_count == 42
    assert resolved_cred.last_used_at is not None
    # Session stamped so app-level 2FA middleware can see it.
    assert session.get("webauthn.assertion_at") is not None


async def test_verify_authentication_rejects_unknown_credential(
    manager: ConnectionManager,
    server: WebauthnServer,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_authentication(monkeypatch)
    async with use_session(manager):
        await server.make_authentication_options()
        from webauthn.helpers.bytes_to_base64url import bytes_to_base64url
        b64 = bytes_to_base64url(b"does-not-exist")
        with pytest.raises(WebauthnCredentialNotFoundError):
            await server.verify_authentication({"id": b64, "rawId": b64})


async def test_challenge_expires_after_ttl(
    manager: ConnectionManager,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = WebauthnServer(
        WebauthnConfig(
            rp_id="localhost",
            rp_name="Test RP",
            challenge_ttl_seconds=1,
        ),
    )
    user_id = await _make_user(manager)
    _patch_registration(monkeypatch)

    async with use_session(manager):
        user = await _load_user(manager, user_id)
        await server.make_registration_options(user)
        # Rewrite the stored timestamp to 5 minutes ago.
        stored = session.get("_webauthn.challenge")
        assert isinstance(stored, dict)
        expired_at = datetime.now(UTC) - timedelta(minutes=5)
        stored["created_at"] = expired_at.isoformat()
        session.put("_webauthn.challenge", stored)

        with pytest.raises(WebauthnChallengeExpiredError):
            await server.verify_registration(user, {"id": "zz"})


async def test_verify_registration_persists_without_outer_transaction(
    manager: ConnectionManager,
    server: WebauthnServer,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression — verify_registration must commit on its own.

    ``DatabaseSessionMiddleware`` deliberately does not auto-commit,
    so a controller that simply awaits ``verify_registration`` without
    wrapping in its own ``transaction()`` used to see the SPA report
    success while the credential silently rolled back. The service
    now owns the commit boundary and persists the row regardless of
    caller behaviour.
    """
    _patch_registration(monkeypatch, credential_id=b"cred-persist")
    user_id = await _make_user(manager)

    async with use_session(manager):
        user = await _load_user(manager, user_id)
        await server.make_registration_options(user)
        # Deliberately no ``async with transaction()`` wrapper here —
        # the service must be self-sufficient.
        await server.verify_registration(
            user, {"id": "AA", "response": {"transports": []}},
        )

    # Fresh session scope — if the row didn't commit, the query
    # below returns empty.
    async with use_session(manager):
        predicate = WebauthnCredential.credential_id == b"cred-persist"  # type: ignore[comparison-overlap]
        found = await WebauthnCredential.query.where(predicate).first()  # type: ignore[arg-type]
        assert found is not None, (
            "verify_registration dropped the credential — commit missing"
        )


async def test_request_origin_override_survives_ports(
    manager: ConnectionManager,
    server: WebauthnServer,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression — the expected_origin handed to py_webauthn must
    carry the request's port so http://localhost:8000 matches.

    Before this fix the server stripped the port and produced
    ["http://localhost", "https://localhost"], which rejected every
    dev-server registration.
    """
    captured: dict[str, object] = {}

    def _fake(*, credential: Any, **kwargs: Any) -> _FakeVerifiedRegistration:
        captured["expected_origin"] = kwargs.get("expected_origin")
        return _FakeVerifiedRegistration(
            credential_id=b"cred-port",
            credential_public_key=b"pk",
            sign_count=0,
            aaguid=None,
            credential_device_type="single_device",
            credential_backed_up=False,
        )

    monkeypatch.setattr(
        server_module, "verify_registration_response", _fake,
    )

    user_id = await _make_user(manager)
    async with use_session(manager):
        user = await _load_user(manager, user_id)
        await server.make_registration_options(user)
        async with transaction():
            await server.verify_registration(
                user,
                {"id": "AA", "response": {}},
                origin="http://localhost:8000",
            )

    assert captured["expected_origin"] == "http://localhost:8000"


async def test_foreign_origin_rejected_despite_override(
    manager: ConnectionManager,
    server: WebauthnServer,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A forged Origin header from an unrelated host must not trick
    the server into trusting it — the rp_id gate falls back to the
    config-derived default rather than forwarding evil.example."""
    captured: dict[str, object] = {}

    def _fake(*, credential: Any, **kwargs: Any) -> _FakeVerifiedRegistration:
        captured["expected_origin"] = kwargs.get("expected_origin")
        return _FakeVerifiedRegistration(
            credential_id=b"cred-foreign",
            credential_public_key=b"pk",
            sign_count=0,
            aaguid=None,
            credential_device_type="single_device",
            credential_backed_up=False,
        )

    monkeypatch.setattr(
        server_module, "verify_registration_response", _fake,
    )

    user_id = await _make_user(manager)
    async with use_session(manager):
        user = await _load_user(manager, user_id)
        await server.make_registration_options(user)
        async with transaction():
            await server.verify_registration(
                user,
                {"id": "AA", "response": {}},
                origin="https://evil.example.com",
            )

    # Config is rp_id=localhost → default list of localhost origins.
    assert captured["expected_origin"] == [
        "http://localhost",
        "https://localhost",
    ]


async def test_wrong_ceremony_label_raises(
    manager: ConnectionManager,
    server: WebauthnServer,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = await _make_user(manager)
    _patch_authentication(monkeypatch)

    async with use_session(manager):
        user = await _load_user(manager, user_id)
        # Start a *registration* ceremony but try to verify an
        # *authentication* — the challenge labels must match.
        await server.make_registration_options(user)
        with pytest.raises(WebauthnChallengeExpiredError):
            await server.verify_authentication({"id": "AA", "rawId": "AA"})
