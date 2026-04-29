"""Pluggable tenant resolvers — three strategies ship in core.

Apps bind whichever resolver they need via the container::

    container.bind(TenantResolver, SubdomainTenantResolver)

The :class:`TenantMiddleware` calls :meth:`resolve` and pins the
result; downstream code reads it via :func:`current_tenant`.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pylar.http.request import Request


@runtime_checkable
class TenantResolver(Protocol):
    """Strategy for extracting the tenant identity from a request."""

    async def resolve(self, request: Request) -> Any | None:
        """Return the :class:`Tenant` for *request*, or ``None``."""
        ...


class SubdomainTenantResolver:
    """Resolve from the first subdomain label: ``acme.example.com`` → ``acme``."""

    async def resolve(self, request: Request) -> Any | None:
        from pylar.tenancy.model import Tenant

        host = request.headers.get("host", "")
        parts = host.split(".")
        if len(parts) < 3:
            return None
        slug = parts[0]
        predicate = Tenant.slug == slug  # type: ignore[comparison-overlap]
        return await Tenant.query.where(predicate).first()  # type: ignore[arg-type]


class HeaderTenantResolver:
    """Resolve from the ``X-Tenant-ID`` header."""

    header: str = "x-tenant-id"

    async def resolve(self, request: Request) -> Any | None:
        from pylar.tenancy.model import Tenant

        slug = request.headers.get(self.header, "").strip()
        if not slug:
            return None
        predicate = Tenant.slug == slug  # type: ignore[comparison-overlap]
        return await Tenant.query.where(predicate).first()  # type: ignore[arg-type]


class PathPrefixTenantResolver:
    """Resolve from ``/t/{slug}/…`` path prefix."""

    prefix: str = "/t/"

    async def resolve(self, request: Request) -> Any | None:
        from pylar.tenancy.model import Tenant

        path = request.url.path
        if not path.startswith(self.prefix):
            return None
        rest = path[len(self.prefix):]
        slug = rest.split("/", 1)[0]
        if not slug:
            return None
        predicate = Tenant.slug == slug  # type: ignore[comparison-overlap]
        return await Tenant.query.where(predicate).first()  # type: ignore[arg-type]
