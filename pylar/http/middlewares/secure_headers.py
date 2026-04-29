"""Add OWASP-recommended security headers to every response.

A single middleware covers the baseline headers that every web
application should send. Override individual attributes on a subclass
to relax specific policies (e.g. allow framing from the same origin)
or set ``None`` to skip a header entirely.
"""

from __future__ import annotations

from pylar.http.middleware import RequestHandler
from pylar.http.request import Request
from pylar.http.response import Response


class SecureHeadersMiddleware:
    """Attach security headers to every outgoing response."""

    #: Prevent the browser from MIME-sniffing the Content-Type.
    x_content_type_options: str | None = "nosniff"

    #: Block the page from being rendered inside an iframe.
    #: ``"DENY"`` is the strictest; ``"SAMEORIGIN"`` allows same-origin
    #: framing.
    x_frame_options: str | None = "DENY"

    #: Enable the XSS filter built into older browsers.
    x_xss_protection: str | None = "1; mode=block"

    #: Tell the browser to only connect over HTTPS once it has seen
    #: this header. ``max-age`` is in seconds; the default is one year.
    #: Set to ``None`` in development (plain HTTP) if needed.
    strict_transport_security: str | None = "max-age=31536000; includeSubDomains"

    #: Control how much referrer information the browser sends.
    referrer_policy: str | None = "strict-origin-when-cross-origin"

    #: Restrict which browser APIs the page can use.  ``None`` skips
    #: the header — set an explicit policy when you know your feature
    #: surface.
    permissions_policy: str | None = None

    #: Content-Security-Policy.  ``None`` skips — CSP is
    #: application-specific and too easy to break with a default.
    content_security_policy: str | None = None

    async def handle(
        self, request: Request, next_handler: RequestHandler
    ) -> Response:
        response = await next_handler(request)
        for header, value in self._headers():
            response.headers.setdefault(header, value)
        return response

    def _headers(self) -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []
        if self.x_content_type_options:
            pairs.append(("X-Content-Type-Options", self.x_content_type_options))
        if self.x_frame_options:
            pairs.append(("X-Frame-Options", self.x_frame_options))
        if self.x_xss_protection:
            pairs.append(("X-XSS-Protection", self.x_xss_protection))
        if self.strict_transport_security:
            pairs.append(("Strict-Transport-Security", self.strict_transport_security))
        if self.referrer_policy:
            pairs.append(("Referrer-Policy", self.referrer_policy))
        if self.permissions_policy:
            pairs.append(("Permissions-Policy", self.permissions_policy))
        if self.content_security_policy:
            pairs.append(("Content-Security-Policy", self.content_security_policy))
        return pairs
