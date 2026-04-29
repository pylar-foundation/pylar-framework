"""Multi-tenancy primitives (ADR-0011 phase 13b).

Ships the column-isolation tier (Tier A) that covers most SaaS
setups: a :class:`Tenant` model, a :class:`TenantMiddleware` that
resolves the active tenant per request, a :class:`TenantScopedMixin`
that auto-scopes every query, and three pluggable resolvers
(subdomain, header, path prefix).

Schema-per-tenant (B) and database-per-tenant (C) are designed in
the ADR but ship in a follow-up once a real project validates on
Postgres.
"""

from pylar.tenancy.context import current_tenant, current_tenant_or_none
from pylar.tenancy.middleware import TenantMiddleware
from pylar.tenancy.mixin import TenantScopedMixin
from pylar.tenancy.model import Tenant
from pylar.tenancy.provider import TenantServiceProvider
from pylar.tenancy.resolvers import (
    HeaderTenantResolver,
    PathPrefixTenantResolver,
    SubdomainTenantResolver,
    TenantResolver,
)

__all__ = [
    "HeaderTenantResolver",
    "PathPrefixTenantResolver",
    "SubdomainTenantResolver",
    "Tenant",
    "TenantMiddleware",
    "TenantResolver",
    "TenantScopedMixin",
    "TenantServiceProvider",
    "current_tenant",
    "current_tenant_or_none",
]
