"""Encrypt outgoing cookie values and decrypt incoming ones.

Mirrors Laravel's ``EncryptCookies`` middleware: every cookie the
application sets is encrypted with the ``APP_KEY`` so the raw value
is never visible in the browser's developer tools. On the way in,
the middleware decrypts the cookie before the request reaches the
controller; cookies that fail decryption (tampered or from a
previous key) are silently dropped so the application sees a fresh
anonymous state.

Cookies listed in :attr:`except_cookies` are passed through
unencrypted — useful for third-party JavaScript that needs to read
a cookie value (analytics, consent banners).
"""

from __future__ import annotations

from http.cookies import SimpleCookie
from typing import ClassVar

from pylar.encryption.encrypter import Encrypter
from pylar.encryption.exceptions import DecryptionError
from pylar.http.middleware import RequestHandler
from pylar.http.request import Request
from pylar.http.response import Response


class EncryptCookiesMiddleware:
    """Encrypt/decrypt cookie values using the bound :class:`Encrypter`."""

    #: Cookie names that should NOT be encrypted (pass-through).
    except_cookies: ClassVar[tuple[str, ...]] = ()

    def __init__(self, encrypter: Encrypter | None = None) -> None:
        self._encrypter = encrypter

    async def handle(
        self, request: Request, next_handler: RequestHandler
    ) -> Response:
        if self._encrypter is None:
            # No APP_KEY configured — pass through unencrypted.
            return await next_handler(request)
        self._decrypt_request_cookies(request)
        response = await next_handler(request)
        self._encrypt_response_cookies(response)
        return response

    # --------------------------------------------------------------- decrypt

    def _decrypt_request_cookies(self, request: Request) -> None:
        """Decrypt cookies in the ASGI scope so controllers see plain values."""
        assert self._encrypter is not None
        raw_headers: list[tuple[bytes, bytes]] = list(
            request.scope.get("headers", [])
        )
        new_headers: list[tuple[bytes, bytes]] = []
        for key, value in raw_headers:
            if key == b"cookie":
                decrypted_cookie = self._decrypt_cookie_header(
                    value.decode("latin-1")
                )
                new_headers.append((key, decrypted_cookie.encode("latin-1")))
            else:
                new_headers.append((key, value))
        request.scope["headers"] = new_headers
        # Clear Starlette's cached cookie dict so it re-parses.
        request.scope.pop("_cookies", None)

    def _decrypt_cookie_header(self, header: str) -> str:
        """Parse a Cookie header, decrypt values, and re-serialize."""
        cookie: SimpleCookie = SimpleCookie()
        cookie.load(header)
        parts: list[str] = []
        for name, morsel in cookie.items():
            if name in self.except_cookies:
                parts.append(f"{name}={morsel.coded_value}")
                continue
            try:
                enc = self._encrypter
                assert enc is not None
                plain = enc.decrypt_string(morsel.value)
                parts.append(f"{name}={plain}")
            except DecryptionError:
                # Tampered or old-key cookie → drop silently.
                pass
        return "; ".join(parts)

    # --------------------------------------------------------------- encrypt

    def _encrypt_response_cookies(self, response: Response) -> None:
        """Encrypt Set-Cookie values on the outgoing response."""
        assert self._encrypter is not None
        raw_headers: list[tuple[bytes, bytes]] = list(response.raw_headers)
        new_raw: list[tuple[bytes, bytes]] = []
        for key, value in raw_headers:
            if key.lower() == b"set-cookie":
                value = self._encrypt_set_cookie(
                    value.decode("latin-1")
                ).encode("latin-1")
            new_raw.append((key, value))
        response.raw_headers = new_raw

    def _encrypt_set_cookie(self, header: str) -> str:
        """Encrypt the value portion of a single Set-Cookie header."""
        # Set-Cookie: name=value; Path=/; ...
        if "=" not in header:
            return header
        name_value, _, attrs = header.partition(";")
        name, _, value = name_value.partition("=")
        name = name.strip()
        value = value.strip()
        if name in self.except_cookies or not value:
            return header
        enc = self._encrypter
        assert enc is not None
        encrypted = enc.encrypt_string(value)
        result = f"{name}={encrypted}"
        if attrs:
            result += f";{attrs}"
        return result
