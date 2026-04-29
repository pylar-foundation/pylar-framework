"""CSRF protection via the double-submit cookie pattern.

Pylar's :class:`CsrfMiddleware` is stateless: it does not need a
session backend. The contract is the standard "double-submit cookie"
recipe used by Django REST Framework, FastAPI security guides, and
the OWASP CSRF cheat sheet:

1. On every safe-method request (``GET``, ``HEAD``, ``OPTIONS``) the
   middleware ensures the response carries a CSRF cookie. If the
   request did not already have one it generates a fresh random token
   and sets the cookie via :meth:`Response.set_cookie`.
2. On every mutating request (``POST``, ``PUT``, ``PATCH``,
   ``DELETE``) the middleware reads the same token from a custom
   header (default ``X-CSRF-Token``) and from the cookie. The two
   must match exactly — :func:`hmac.compare_digest` keeps the check
   constant-time. A mismatch raises :class:`pylar.http.Forbidden`,
   which the route compiler renders as a 403.

The token is a URL-safe random string. Because the cookie is set with
``HttpOnly=False`` (the browser-side JavaScript needs to read it to
echo into the header), it is **not** itself a credential — it just
forces the attacker to read a value from a victim domain, which the
same-origin policy makes impossible. Combined with cookie attributes
``SameSite=Lax`` and ``Secure`` (the latter optional but encouraged
in production) this is enough to defeat the typical CSRF attack
surface.
"""

from __future__ import annotations

import hmac
import secrets
from typing import Literal

from pylar.http.exceptions import Forbidden
from pylar.http.middleware import RequestHandler
from pylar.http.request import Request
from pylar.http.response import Response

#: Valid values for the SameSite cookie attribute.
SameSite = Literal["lax", "strict", "none"]


class CsrfMiddleware:
    """Stateless CSRF protection middleware (double-submit cookie)."""

    SAFE_METHODS: frozenset[str] = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

    def __init__(
        self,
        *,
        cookie_name: str = "pylar_csrf",
        header_name: str = "x-csrf-token",
        cookie_max_age: int = 60 * 60 * 24 * 7,  # one week
        secure: bool = False,
        same_site: SameSite = "lax",
    ) -> None:
        self._cookie_name = cookie_name
        self._header_name = header_name.lower()
        self._cookie_max_age = cookie_max_age
        self._secure = secure
        self._same_site = same_site

    async def handle(self, request: Request, next_handler: RequestHandler) -> Response:
        cookie_token = request.cookies.get(self._cookie_name)

        if request.method.upper() not in self.SAFE_METHODS:
            self._verify(cookie_token, request.headers.get(self._header_name))

        response = await next_handler(request)

        # Rotate the token after every mutating request so a leaked
        # token is usable only once. On safe methods, set a token only
        # if the cookie is missing (first visit).
        should_rotate = (
            request.method.upper() not in self.SAFE_METHODS or not cookie_token
        )
        if should_rotate:
            new_token = secrets.token_urlsafe(32)
            response.set_cookie(
                key=self._cookie_name,
                value=new_token,
                max_age=self._cookie_max_age,
                httponly=False,
                secure=self._secure,
                samesite=self._same_site,
            )

        return response

    def _verify(self, cookie_token: str | None, header_token: str | None) -> None:
        if not cookie_token or not header_token:
            raise Forbidden("CSRF token missing")
        if not hmac.compare_digest(cookie_token, header_token):
            raise Forbidden("CSRF token mismatch")
