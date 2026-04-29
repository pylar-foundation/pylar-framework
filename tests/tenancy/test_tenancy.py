"""Tests for multi-tenancy (ADR-0011 phase 13b)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import ClassVar

import pytest

from pylar.database import (
    ConnectionManager,
    DatabaseConfig,
    Model,
    fields,
    transaction,
)
from pylar.database.session import use_session
from pylar.tenancy import (
    HeaderTenantResolver,
    PathPrefixTenantResolver,
    SubdomainTenantResolver,
    Tenant,
    TenantMiddleware,
    TenantScopedMixin,
    current_tenant,
    current_tenant_or_none,
)
from pylar.tenancy.context import set_current_tenant


class _ScopedPost(Model, TenantScopedMixin, metaclass=type(Model)):  # type: ignore[misc]
    class Meta:
        db_table = "tenant_scoped_posts"

    tenant_id = fields.IntegerField(index=True)
    title = fields.CharField(max_length=200)


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


async def _seed_tenants(manager: ConnectionManager) -> tuple[object, object]:
    """Create two tenants and return their ids."""
    async with use_session(manager):
        async with transaction():
            t1 = Tenant(slug="acme", name="Acme Corp")
            await Tenant.query.save(t1)
            t2 = Tenant(slug="globex", name="Globex Inc")
            await Tenant.query.save(t2)
            return t1.id, t2.id


# ------------------------------------------------ context var


def test_current_tenant_raises_when_unset() -> None:
    set_current_tenant(None)
    with pytest.raises(RuntimeError, match="No active tenant"):
        current_tenant()


def test_current_tenant_or_none_returns_none_when_unset() -> None:
    set_current_tenant(None)
    assert current_tenant_or_none() is None


# ------------------------------------------------ middleware


class _FakeReq:
    def __init__(self, headers: dict[str, str]) -> None:
        self.headers = {k.lower(): v for k, v in headers.items()}


async def test_middleware_pins_tenant_for_handler(
    manager: ConnectionManager,
) -> None:
    _t1_id, _ = await _seed_tenants(manager)

    captured: list[object] = []

    async def handler(req: object) -> str:
        captured.append(current_tenant())
        return "ok"

    resolver = HeaderTenantResolver()
    mw = TenantMiddleware(resolver)

    async with use_session(manager):
        req = _FakeReq({"X-Tenant-ID": "acme"})
        result = await mw.handle(req, handler)  # type: ignore[arg-type]

    assert result == "ok"
    assert getattr(captured[0], "slug", None) == "acme"
    # After the middleware exits, the tenant is reset.
    assert current_tenant_or_none() is None


async def test_middleware_returns_404_on_missing_tenant(
    manager: ConnectionManager,
) -> None:
    await _seed_tenants(manager)
    resolver = HeaderTenantResolver()
    mw = TenantMiddleware(resolver)

    async with use_session(manager):
        req = _FakeReq({"X-Tenant-ID": "nonexistent"})
        response = await mw.handle(req, _boom)  # type: ignore[arg-type]

    assert response.status_code == 404


async def _boom(req: object) -> object:
    raise AssertionError("next_handler should not have been called")


# ------------------------------------------------ resolvers


async def test_header_resolver(manager: ConnectionManager) -> None:
    await _seed_tenants(manager)
    resolver = HeaderTenantResolver()

    async with use_session(manager):
        result = await resolver.resolve(_FakeReq({"X-Tenant-ID": "acme"}))  # type: ignore[arg-type]
        assert result is not None
        assert result.slug == "acme"

        miss = await resolver.resolve(_FakeReq({}))  # type: ignore[arg-type]
        assert miss is None


async def test_subdomain_resolver(manager: ConnectionManager) -> None:
    await _seed_tenants(manager)
    resolver = SubdomainTenantResolver()

    class _SubReq:
        headers: ClassVar[dict[str, str]] = {"host": "acme.example.com"}

    async with use_session(manager):
        result = await resolver.resolve(_SubReq())  # type: ignore[arg-type]
        assert result is not None
        assert result.slug == "acme"


async def test_path_prefix_resolver(manager: ConnectionManager) -> None:
    await _seed_tenants(manager)
    resolver = PathPrefixTenantResolver()

    class _PathReq:
        class Url:
            path = "/t/globex/posts"

        url = Url

    async with use_session(manager):
        result = await resolver.resolve(_PathReq())  # type: ignore[arg-type]
        assert result is not None
        assert result.slug == "globex"


# ------------------------------------------------ scoped mixin


async def test_scoped_mixin_stamps_tenant_id_on_save(
    manager: ConnectionManager,
) -> None:
    t1_id, _ = await _seed_tenants(manager)
    async with use_session(manager):
        t1 = await Tenant.query.get(t1_id)

    set_current_tenant(t1)
    try:
        async with use_session(manager):
            async with transaction():
                post = _ScopedPost(title="Scoped post")
                post._stamp_tenant_id()
                assert post.tenant_id == t1_id
    finally:
        set_current_tenant(None)


async def test_scoped_mixin_filter_returns_predicate(
    manager: ConnectionManager,
) -> None:
    t1_id, _ = await _seed_tenants(manager)
    async with use_session(manager):
        t1 = await Tenant.query.get(t1_id)

    set_current_tenant(t1)
    try:
        predicate = _ScopedPost._tenant_scope_filter()
        assert predicate is not None
    finally:
        set_current_tenant(None)


async def test_scoped_mixin_filter_is_none_without_tenant() -> None:
    set_current_tenant(None)
    predicate = _ScopedPost._tenant_scope_filter()
    assert predicate is None
