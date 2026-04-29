"""Ambient tenant context — same pattern as ``current_session`` and
``current_user``.

The :class:`TenantMiddleware` sets the active tenant on every
request; downstream code reads it via :func:`current_tenant` or
:func:`current_tenant_or_none`.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pylar.tenancy.model import Tenant

_current_tenant: ContextVar[Tenant | None] = ContextVar(
    "pylar_current_tenant", default=None,
)


def current_tenant() -> Tenant:
    """Return the active tenant or raise."""
    tenant = _current_tenant.get()
    if tenant is None:
        raise RuntimeError(
            "No active tenant. Wrap the request in TenantMiddleware "
            "or set the tenant explicitly with set_current_tenant()."
        )
    return tenant


def current_tenant_or_none() -> Tenant | None:
    return _current_tenant.get()


def set_current_tenant(tenant: Tenant | None) -> None:
    """Explicitly set the active tenant — used by middleware and tests."""
    _current_tenant.set(tenant)
