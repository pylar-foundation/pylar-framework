"""HTTP middleware that resolves and pins the active tenant."""

from __future__ import annotations

from pylar.http.middleware import RequestHandler
from pylar.http.request import Request
from pylar.http.response import JsonResponse, Response
from pylar.tenancy.context import _current_tenant
from pylar.tenancy.resolvers import TenantResolver


class TenantMiddleware:
    """Resolve the tenant and install it in the contextvar for the request.

    Place early in the middleware stack — before database, auth, and
    application middleware — so every downstream layer sees the active
    tenant via :func:`current_tenant`.

    When resolution fails (no matching tenant, header/subdomain
    missing) the middleware returns a JSON 404 and short-circuits the
    pipeline. Override :meth:`on_missing` for custom behaviour.
    """

    def __init__(self, resolver: TenantResolver) -> None:
        self._resolver = resolver

    async def handle(
        self, request: Request, next_handler: RequestHandler,
    ) -> Response:
        tenant = await self._resolver.resolve(request)
        if tenant is None:
            return self.on_missing(request)
        token = _current_tenant.set(tenant)
        try:
            return await next_handler(request)
        finally:
            _current_tenant.reset(token)

    def on_missing(self, request: Request) -> Response:
        """Called when the resolver returns ``None``.

        Override for custom behaviour (redirect to a sign-up page,
        return an HTML error, etc.).
        """
        return JsonResponse(
            content={
                "error": {
                    "code": "tenant_not_found",
                    "message": "Could not identify the tenant for this request.",
                },
            },
            status_code=404,
        )
