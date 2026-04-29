"""Roles + permissions (ADR-0009 phase 11e).

Four small SA-mapped models plus a handful of narrow helpers give
pylar the role/permission surface every production app eventually
needs:

* :class:`Role` — named group (``"admin"``, ``"editor"``, …).
* :class:`Permission` — fine-grained capability (``"posts.edit"``).
* :class:`UserRole` — pivot, ``user_id ↔ role_id``.
* :class:`RolePermission` — pivot, ``role_id ↔ permission_id``.

``user_id`` is stored as a string so the same tables accept integer
PKs, UUIDs, or anything else an application's user model uses.

The helper functions :func:`assign_role` / :func:`revoke_role` /
:func:`has_role` / :func:`has_permission` / :func:`user_permissions`
work on any :class:`Authenticatable` — same contract the rest of the
auth layer consumes.

Gate integration: :class:`pylar.auth.Gate` keeps its ability
callback API unchanged. A policy that wants a permission check
writes::

    from pylar.auth.roles import has_permission

    class PostPolicy:
        async def edit(self, user: User, post: Post) -> bool:
            return await has_permission(user, "posts.edit")

— no new framework glue, just a call into this module.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, cast

from pylar.auth.contracts import Authenticatable
from pylar.database import Model, fields

# -------------------------------------------------------------- models


class Role(Model):  # type: ignore[metaclass]
    """A named group of permissions."""

    class Meta:
        db_table = "pylar_roles"

    name = fields.CharField(max_length=64, unique=True, index=True)
    label = fields.CharField(max_length=128, null=True)


class Permission(Model):  # type: ignore[metaclass]
    """A fine-grained capability, referenced by string ``code``."""

    class Meta:
        db_table = "pylar_permissions"

    code = fields.CharField(max_length=128, unique=True, index=True)
    label = fields.CharField(max_length=128, null=True)


class UserRole(Model):  # type: ignore[metaclass]
    """Pivot row attaching a :class:`Role` to a concrete user PK.

    ``user_id`` is stringified so the same table carries integer,
    UUID, or any other primary-key flavour.
    """

    class Meta:
        db_table = "pylar_user_roles"

    user_id = fields.CharField(max_length=64, index=True)
    role_id = fields.IntegerField(index=True)


class RolePermission(Model):  # type: ignore[metaclass]
    """Pivot row attaching a :class:`Permission` to a :class:`Role`."""

    class Meta:
        db_table = "pylar_role_permissions"

    role_id = fields.IntegerField(index=True)
    permission_id = fields.IntegerField(index=True)


# -------------------------------------------------- column-expression escape hatch
#
# Every .query.where(...) call on a Django-style Field column produces
# a SA ColumnElement at runtime, but mypy sees the fields as their
# wrapper classes and resolves ``==`` to ``bool``. Rather than sprinkle
# ``type: ignore`` across every helper, the whole file funnels its
# predicates through :func:`_col` — a single ``Any``-returning escape
# hatch so the ignores land once.


def _col(expr: Any) -> Any:
    return expr


def _attr(cls: type, name: str) -> Any:
    """Return a Field descriptor as Any so SA ops like ``.in_`` type-check."""
    return getattr(cls, name)


# ---------------------------------------------------------- helpers


async def _resolve_role(role_or_name: Role | str) -> Role | None:
    if isinstance(role_or_name, Role):
        return role_or_name
    return await Role.query.where(
        _col(_attr(Role, "name") == role_or_name),
    ).first()


async def _resolve_permission(perm_or_code: Permission | str) -> Permission | None:
    if isinstance(perm_or_code, Permission):
        return perm_or_code
    return await Permission.query.where(
        _col(_attr(Permission, "code") == perm_or_code),
    ).first()


def _user_key(user: Authenticatable) -> str:
    return str(user.auth_identifier)


async def assign_role(user: Authenticatable, role: Role | str) -> None:
    """Attach *role* to *user*; idempotent (no duplicate pivot rows)."""
    resolved = await _resolve_role(role)
    if resolved is None:
        raise LookupError(f"role not found: {role!r}")
    role_id = int(cast(Any, resolved).id)
    user_id = _user_key(user)

    existing = await (
        UserRole.query.where(_col(_attr(UserRole, "user_id") ==user_id))
        .where(_col(_attr(UserRole, "role_id") ==role_id))
        .first()
    )
    if existing is not None:
        return
    await UserRole.query.save(UserRole(user_id=user_id, role_id=role_id))


async def revoke_role(user: Authenticatable, role: Role | str) -> None:
    """Detach *role* from *user*; no-op when the pivot row is absent."""
    resolved = await _resolve_role(role)
    if resolved is None:
        return
    pivot = await (
        UserRole.query.where(_col(_attr(UserRole, "user_id") ==_user_key(user)))
        .where(_col(_attr(UserRole, "role_id") ==int(cast(Any, resolved).id)))
        .first()
    )
    if pivot is not None:
        await UserRole.query.delete(pivot)


async def grant_permission(role: Role | str, permission: Permission | str) -> None:
    """Attach *permission* to *role*; idempotent."""
    resolved_role = await _resolve_role(role)
    resolved_perm = await _resolve_permission(permission)
    if resolved_role is None or resolved_perm is None:
        raise LookupError("role or permission not found")
    role_id = int(cast(Any, resolved_role).id)
    perm_id = int(cast(Any, resolved_perm).id)

    existing = await (
        RolePermission.query.where(_col(_attr(RolePermission, "role_id") ==role_id))
        .where(_col(_attr(RolePermission, "permission_id") ==perm_id))
        .first()
    )
    if existing is not None:
        return
    await RolePermission.query.save(
        RolePermission(role_id=role_id, permission_id=perm_id)
    )


async def revoke_permission(role: Role | str, permission: Permission | str) -> None:
    """Detach *permission* from *role*; no-op when absent."""
    resolved_role = await _resolve_role(role)
    resolved_perm = await _resolve_permission(permission)
    if resolved_role is None or resolved_perm is None:
        return
    pivot = await (
        RolePermission.query.where(
            _col(_attr(RolePermission, "role_id") ==int(cast(Any, resolved_role).id)),
        )
        .where(
            _col(
                _attr(RolePermission, "permission_id")
                == int(cast(Any, resolved_perm).id)
            ),
        )
        .first()
    )
    if pivot is not None:
        await RolePermission.query.delete(pivot)


# ------------------------------------------------------------- queries


async def user_role_ids(user: Authenticatable) -> list[int]:
    """Return every role id pinned on *user*. Cheap — one SELECT."""
    pivots = await UserRole.query.where(
        _col(_attr(UserRole, "user_id") ==_user_key(user)),
    ).all()
    return [int(p.role_id) for p in pivots]


async def user_roles(user: Authenticatable) -> list[Role]:
    """Return the :class:`Role` objects attached to *user*."""
    ids = await user_role_ids(user)
    if not ids:
        return []
    return list(
        await Role.query.where(_col(_attr(Role, "id").in_(ids))).all(),
    )


async def user_permissions(user: Authenticatable) -> list[str]:
    """Return the de-duplicated permission codes granted via any of
    *user*'s roles. Two SELECTs total regardless of role count."""
    role_ids = await user_role_ids(user)
    if not role_ids:
        return []
    pivots = await RolePermission.query.where(
        _col(_attr(RolePermission, "role_id").in_(role_ids)),
    ).all()
    perm_ids = {int(p.permission_id) for p in pivots}
    if not perm_ids:
        return []
    perms = await Permission.query.where(
        _col(_attr(Permission, "id").in_(perm_ids)),
    ).all()
    return sorted({str(p.code) for p in perms})


async def has_role(user: Authenticatable, role: Role | str) -> bool:
    """Does *user* carry *role*? Accepts Role instance or name."""
    resolved = await _resolve_role(role)
    if resolved is None:
        return False
    pivot = await (
        UserRole.query.where(_col(_attr(UserRole, "user_id") ==_user_key(user)))
        .where(_col(_attr(UserRole, "role_id") ==int(cast(Any, resolved).id)))
        .first()
    )
    return pivot is not None


async def has_permission(
    user: Authenticatable, permission: Permission | str,
) -> bool:
    """Does any role attached to *user* carry *permission*?

    Permission codes also support a wildcard suffix — a role that
    holds ``posts.*`` grants ``posts.edit`` / ``posts.delete`` etc.,
    mirroring the ability-matching rule on :class:`ApiToken`.
    """
    code = permission if isinstance(permission, str) else str(
        getattr(permission, "code", "")
    )
    if not code:
        return False
    granted = await user_permissions(user)
    if code in granted:
        return True
    for prefix in _wildcard_prefixes(granted):
        if code.startswith(prefix):
            return True
    return False


def _wildcard_prefixes(codes: Iterable[str]) -> list[str]:
    """Strip the trailing ``.*`` off wildcard codes for prefix matching."""
    return [c[:-1] for c in codes if c.endswith(".*")]


__all__ = [
    "Permission",
    "Role",
    "RolePermission",
    "UserRole",
    "assign_role",
    "grant_permission",
    "has_permission",
    "has_role",
    "revoke_permission",
    "revoke_role",
    "user_permissions",
    "user_role_ids",
    "user_roles",
]
