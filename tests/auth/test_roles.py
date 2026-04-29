"""Tests for roles + permissions (ADR-0009 phase 11e)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from pylar.auth import (
    Permission,
    Role,
    assign_role,
    grant_permission,
    has_permission,
    has_role,
    revoke_permission,
    revoke_role,
    user_permissions,
    user_roles,
)
from pylar.database import (
    ConnectionManager,
    DatabaseConfig,
    Model,
    fields,
    transaction,
)
from pylar.database.session import use_session


class _RoleUser(Model, metaclass=type(Model)):  # type: ignore[misc]
    class Meta:
        db_table = "role_test_users"

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


async def _seed(manager: ConnectionManager) -> dict[str, object]:
    """Build a realistic 2-user, 3-role, 3-permission fixture."""
    async with use_session(manager):
        async with transaction():
            alice = _RoleUser(name="Alice")
            await _RoleUser.query.save(alice)
            bob = _RoleUser(name="Bob")
            await _RoleUser.query.save(bob)

            admin = Role(name="admin", label="Administrator")
            await Role.query.save(admin)
            editor = Role(name="editor", label="Editor")
            await Role.query.save(editor)
            viewer = Role(name="viewer", label="Viewer")
            await Role.query.save(viewer)

            edit_posts = Permission(code="posts.edit", label="Edit posts")
            await Permission.query.save(edit_posts)
            delete_posts = Permission(
                code="posts.delete", label="Delete posts",
            )
            await Permission.query.save(delete_posts)
            view_dashboard = Permission(
                code="dashboard.view", label="View dashboard",
            )
            await Permission.query.save(view_dashboard)

            return {
                "alice": alice,
                "bob": bob,
                "admin": admin,
                "editor": editor,
                "viewer": viewer,
            }


# ------------------------------------------------------- assignment


async def test_assign_and_has_role(manager: ConnectionManager) -> None:
    seed = await _seed(manager)
    async with use_session(manager):
        async with transaction():
            await assign_role(seed["alice"], "admin")  # type: ignore[arg-type]

    async with use_session(manager):
        assert await has_role(seed["alice"], "admin") is True  # type: ignore[arg-type]
        assert await has_role(seed["alice"], "viewer") is False  # type: ignore[arg-type]
        assert await has_role(seed["bob"], "admin") is False  # type: ignore[arg-type]


async def test_assign_role_is_idempotent(manager: ConnectionManager) -> None:
    seed = await _seed(manager)
    async with use_session(manager):
        async with transaction():
            await assign_role(seed["alice"], "editor")  # type: ignore[arg-type]
            await assign_role(seed["alice"], "editor")  # type: ignore[arg-type]

    async with use_session(manager):
        roles = await user_roles(seed["alice"])  # type: ignore[arg-type]
        editor_count = sum(
            1 for r in roles if r.name == "editor"
        )
        assert editor_count == 1


async def test_assign_unknown_role_raises(manager: ConnectionManager) -> None:
    seed = await _seed(manager)
    async with use_session(manager):
        async with transaction():
            with pytest.raises(LookupError):
                await assign_role(seed["alice"], "nonexistent")  # type: ignore[arg-type]


async def test_revoke_role_removes_pivot(manager: ConnectionManager) -> None:
    seed = await _seed(manager)
    async with use_session(manager):
        async with transaction():
            await assign_role(seed["alice"], "admin")  # type: ignore[arg-type]
            await revoke_role(seed["alice"], "admin")  # type: ignore[arg-type]

    async with use_session(manager):
        assert await has_role(seed["alice"], "admin") is False  # type: ignore[arg-type]


async def test_revoke_missing_role_is_noop(manager: ConnectionManager) -> None:
    seed = await _seed(manager)
    async with use_session(manager):
        async with transaction():
            # Doesn't raise even though alice doesn't have the role.
            await revoke_role(seed["alice"], "viewer")  # type: ignore[arg-type]


# ------------------------------------------------------- permissions


async def test_permission_grant_and_check(manager: ConnectionManager) -> None:
    seed = await _seed(manager)
    async with use_session(manager):
        async with transaction():
            await grant_permission("editor", "posts.edit")
            await assign_role(seed["alice"], "editor")  # type: ignore[arg-type]

    async with use_session(manager):
        assert await has_permission(seed["alice"], "posts.edit") is True  # type: ignore[arg-type]
        assert await has_permission(seed["alice"], "posts.delete") is False  # type: ignore[arg-type]
        assert await has_permission(seed["bob"], "posts.edit") is False  # type: ignore[arg-type]


async def test_permission_wildcard_grants_prefix(
    manager: ConnectionManager,
) -> None:
    seed = await _seed(manager)
    async with use_session(manager):
        async with transaction():
            await Permission.query.save(
                Permission(code="posts.*", label="All posts abilities"),
            )
            await grant_permission("admin", "posts.*")
            await assign_role(seed["alice"], "admin")  # type: ignore[arg-type]

    async with use_session(manager):
        assert await has_permission(seed["alice"], "posts.edit") is True  # type: ignore[arg-type]
        assert await has_permission(seed["alice"], "posts.delete") is True  # type: ignore[arg-type]
        # Not a posts.* prefix:
        assert await has_permission(seed["alice"], "users.manage") is False  # type: ignore[arg-type]


async def test_user_permissions_aggregates_across_roles(
    manager: ConnectionManager,
) -> None:
    seed = await _seed(manager)
    async with use_session(manager):
        async with transaction():
            await grant_permission("editor", "posts.edit")
            await grant_permission("viewer", "dashboard.view")
            await assign_role(seed["alice"], "editor")  # type: ignore[arg-type]
            await assign_role(seed["alice"], "viewer")  # type: ignore[arg-type]

    async with use_session(manager):
        perms = await user_permissions(seed["alice"])  # type: ignore[arg-type]
        assert perms == ["dashboard.view", "posts.edit"]


async def test_revoke_permission_removes_pivot(
    manager: ConnectionManager,
) -> None:
    seed = await _seed(manager)
    async with use_session(manager):
        async with transaction():
            await grant_permission("editor", "posts.edit")
            await assign_role(seed["alice"], "editor")  # type: ignore[arg-type]
            await revoke_permission("editor", "posts.edit")

    async with use_session(manager):
        assert await has_permission(seed["alice"], "posts.edit") is False  # type: ignore[arg-type]


async def test_has_permission_on_user_without_roles_is_false(
    manager: ConnectionManager,
) -> None:
    seed = await _seed(manager)
    async with use_session(manager):
        assert await has_permission(seed["bob"], "anything") is False  # type: ignore[arg-type]
        assert await user_permissions(seed["bob"]) == []  # type: ignore[arg-type]
