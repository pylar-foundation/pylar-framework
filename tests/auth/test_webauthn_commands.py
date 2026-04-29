"""Tests for the ``auth:webauthn:*`` console commands (ADR-0013 phase 15c)."""

from __future__ import annotations

import io
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest

from pylar.auth.webauthn import WebauthnCredential
from pylar.auth.webauthn.commands import (
    WebauthnListCommand,
    WebauthnPruneCommand,
    WebauthnRevokeCommand,
    _WebauthnListInput,
    _WebauthnPruneInput,
    _WebauthnRevokeInput,
)
from pylar.console.output import Output
from pylar.database import (
    ConnectionManager,
    DatabaseConfig,
    Model,
    transaction,
)
from pylar.database.session import use_session


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


async def _make_credential(
    *,
    tokenable_id: str = "1",
    nickname: str | None = "Laptop",
    last_used_at: datetime | None = None,
    created_at: datetime | None = None,
) -> WebauthnCredential:
    cred = WebauthnCredential(
        tokenable_type="tests.auth.test_webauthn_commands._FakeUser",
        tokenable_id=tokenable_id,
        credential_id=b"cred-" + tokenable_id.encode(),
        public_key=b"pubkey",
        sign_count=0,
        aaguid="00000000-0000-0000-0000-000000000001",
        transports="[]",
        backup_eligible=True,
        backup_state=False,
        nickname=nickname,
        last_used_at=last_used_at,
    )
    async with transaction():
        await WebauthnCredential.query.save(cred)
    # Force an explicit created_at for the prune tests when asked.
    if created_at is not None:
        cred.created_at = created_at  # type: ignore[assignment]
        async with transaction():
            await WebauthnCredential.query.save(cred)
    return cred


def _capture_output() -> tuple[Output, io.StringIO]:
    buffer = io.StringIO()
    output = Output(writer=buffer, colour=False)
    return output, buffer


# ------------------------------------------------- list


async def test_list_empty(manager: ConnectionManager) -> None:
    async with use_session(manager):
        out, buf = _capture_output()
        code = await WebauthnListCommand(out).handle(_WebauthnListInput())
    assert code == 0
    assert "No WebAuthn credentials" in buf.getvalue()


async def test_list_table_contains_every_registered_credential(
    manager: ConnectionManager,
) -> None:
    async with use_session(manager):
        await _make_credential(tokenable_id="1", nickname="Alice phone")
        await _make_credential(tokenable_id="2", nickname="Bob laptop")

        out, buf = _capture_output()
        code = await WebauthnListCommand(out).handle(_WebauthnListInput())

    assert code == 0
    text = buf.getvalue()
    assert "Alice phone" in text
    assert "Bob laptop" in text


async def test_list_filters_by_user_id(manager: ConnectionManager) -> None:
    async with use_session(manager):
        await _make_credential(tokenable_id="1", nickname="Alice phone")
        await _make_credential(tokenable_id="2", nickname="Bob laptop")

        out, buf = _capture_output()
        code = await WebauthnListCommand(out).handle(
            _WebauthnListInput(user_id="1"),
        )

    assert code == 0
    text = buf.getvalue()
    assert "Alice phone" in text
    assert "Bob laptop" not in text


# ------------------------------------------------ revoke


async def test_revoke_deletes_credential(manager: ConnectionManager) -> None:
    async with use_session(manager):
        cred = await _make_credential()
        pk = int(cred.id)

        out, buf = _capture_output()
        async with transaction():
            code = await WebauthnRevokeCommand(out).handle(
                _WebauthnRevokeInput(credential_id=str(pk)),
            )

    assert code == 0
    assert "Revoked credential" in buf.getvalue()
    async with use_session(manager):
        from pylar.database.exceptions import RecordNotFoundError
        with pytest.raises(RecordNotFoundError):
            await WebauthnCredential.query.get(pk)


async def test_revoke_missing_credential_reports_error(
    manager: ConnectionManager,
) -> None:
    async with use_session(manager):
        out, buf = _capture_output()
        async with transaction():
            code = await WebauthnRevokeCommand(out).handle(
                _WebauthnRevokeInput(credential_id="999"),
            )

    assert code == 1
    assert "No credential with id 999" in buf.getvalue()


async def test_revoke_rejects_non_integer(manager: ConnectionManager) -> None:
    out, buf = _capture_output()
    code = await WebauthnRevokeCommand(out).handle(
        _WebauthnRevokeInput(credential_id="abc"),
    )
    assert code == 1
    assert "must be an integer" in buf.getvalue()


# ------------------------------------------------- prune


async def test_prune_drops_stale_credentials(manager: ConnectionManager) -> None:
    async with use_session(manager):
        ancient = datetime.now(UTC) - timedelta(days=365)
        recent = datetime.now(UTC) - timedelta(days=10)
        await _make_credential(
            tokenable_id="1", last_used_at=ancient, created_at=ancient,
        )
        await _make_credential(
            tokenable_id="2", last_used_at=recent,
        )

        out, buf = _capture_output()
        async with transaction():
            code = await WebauthnPruneCommand(out).handle(
                _WebauthnPruneInput(days=180),
            )

    assert code == 0
    assert "Pruned 1 credential" in buf.getvalue()
    async with use_session(manager):
        remaining = await WebauthnCredential.query.all()
        tokenable_ids = sorted(c.tokenable_id for c in remaining)
        assert tokenable_ids == ["2"]


async def test_prune_noop_when_everything_fresh(manager: ConnectionManager) -> None:
    async with use_session(manager):
        await _make_credential()

        out, buf = _capture_output()
        async with transaction():
            code = await WebauthnPruneCommand(out).handle(
                _WebauthnPruneInput(days=180),
            )

    assert code == 0
    assert "No credentials older than 180 days" in buf.getvalue()


async def test_prune_rejects_non_positive_days(manager: ConnectionManager) -> None:
    out, buf = _capture_output()
    code = await WebauthnPruneCommand(out).handle(
        _WebauthnPruneInput(days=0),
    )
    assert code == 1
    assert "must be a positive integer" in buf.getvalue()
