"""Restore the real client IP and scheme behind a reverse proxy.

When the application sits behind nginx, an AWS ALB, or Cloudflare the
ASGI server sees the proxy's IP in ``request.client.host`` and
``http`` as the scheme even though the end user connected over HTTPS.
This middleware reads the de-facto standard ``X-Forwarded-*`` headers
and patches the request's ASGI scope so downstream code (throttle
middleware, audit logs, ``request.url.scheme``) sees the correct
values.

Subclass and override :attr:`trusted_proxies` to restrict which
source IPs are allowed to set the headers — the default ``("*",)``
trusts everyone, which is fine when the proxy is the only network
path to the application (e.g. a container behind an ALB) but
dangerous when end users can reach the app directly.
"""

from __future__ import annotations

from pylar.http.middleware import RequestHandler
from pylar.http.request import Request
from pylar.http.response import Response


class TrustProxiesMiddleware:
    """Read ``X-Forwarded-For/Proto/Host`` and patch the ASGI scope."""

    #: IP addresses allowed to set forwarded headers. Empty by default
    #: (trust nobody). Set to ``("*",)`` to trust any source (only
    #: safe when the proxy is the sole ingress path, e.g. behind an
    #: ALB), or list concrete IPs like ``("10.0.0.1", "10.0.0.2")``.
    trusted_proxies: tuple[str, ...] = ()

    #: Header carrying the original client IP.
    forwarded_for_header: str = "x-forwarded-for"

    #: Header carrying the original scheme (``https``).
    forwarded_proto_header: str = "x-forwarded-proto"

    #: Header carrying the original ``Host`` value.
    forwarded_host_header: str = "x-forwarded-host"

    async def handle(
        self, request: Request, next_handler: RequestHandler
    ) -> Response:
        if not self._is_trusted(request):
            return await next_handler(request)

        # Patch client IP.
        forwarded_for = request.headers.get(self.forwarded_for_header)
        if forwarded_for:
            real_ip = forwarded_for.split(",")[0].strip()
            client = request.scope.get("client")
            if client:
                request.scope["client"] = (real_ip, client[1])
            else:
                request.scope["client"] = (real_ip, 0)

        # Patch scheme.
        forwarded_proto = request.headers.get(self.forwarded_proto_header)
        if forwarded_proto:
            request.scope["scheme"] = forwarded_proto.strip().lower()

        # Patch host header.
        forwarded_host = request.headers.get(self.forwarded_host_header)
        if forwarded_host:
            # Starlette reads host from the raw headers list.
            raw_headers: list[tuple[bytes, bytes]] = list(
                request.scope.get("headers", [])
            )
            raw_headers = [
                (k, v) for k, v in raw_headers if k != b"host"
            ]
            raw_headers.append((b"host", forwarded_host.strip().encode("latin-1")))
            request.scope["headers"] = raw_headers

        return await next_handler(request)

    def _is_trusted(self, request: Request) -> bool:
        if not self.trusted_proxies:
            return False
        if "*" in self.trusted_proxies:
            return True
        client = request.scope.get("client")
        if not client:
            return False
        client_ip = client[0]
        for entry in self.trusted_proxies:
            if "/" in entry:
                if _ip_in_cidr(client_ip, entry):
                    return True
            elif client_ip == entry:
                return True
        return False


def _ip_in_cidr(ip: str, cidr: str) -> bool:
    """Check if *ip* falls within *cidr* (e.g. ``10.0.0.0/8``)."""
    import ipaddress

    try:
        return ipaddress.ip_address(ip) in ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return False
