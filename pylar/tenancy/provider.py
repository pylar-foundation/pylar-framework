"""``TenantServiceProvider`` — wires the tenancy layer."""

from __future__ import annotations

from pylar.foundation.container import Container
from pylar.foundation.provider import ServiceProvider
from pylar.tenancy.middleware import TenantMiddleware
from pylar.tenancy.resolvers import HeaderTenantResolver, TenantResolver


class TenantServiceProvider(ServiceProvider):
    """Register the tenancy primitives.

    Binds a default :class:`HeaderTenantResolver` so the middleware
    can be used immediately. Apps override with their preferred
    resolver (subdomain, path prefix) via a container rebinding in
    their own provider.
    """

    def register(self, container: Container) -> None:
        if not container.has(TenantResolver):
            container.bind(TenantResolver, HeaderTenantResolver)  # type: ignore[type-abstract]
        container.bind(TenantMiddleware, TenantMiddleware)
