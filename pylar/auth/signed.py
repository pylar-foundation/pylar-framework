"""HMAC-signed, optionally-expiring URLs (ADR-0009 phase 11a).

Signed URLs are the primitive the email-verification and password-reset
flows use to let a random client click a link and have the framework
trust the payload. The signature is a SHA-256 HMAC of the canonical
query string (sorted, URL-encoded) keyed on the application's
``APP_KEY``. Rotating ``APP_KEY`` invalidates every outstanding link.

Usage::

    signer: UrlSigner  # auto-wired

    link = signer.sign(
        "/auth/verify",
        params={"user_id": "42"},
        expires_in=timedelta(hours=24),
    )

    # Later, inside the controller:
    try:
        params = signer.verify("/auth/verify", request.query_params)
    except InvalidSignature:
        return json({"error": "link_tampered"}, status=400)
    except ExpiredSignature:
        return json({"error": "link_expired"}, status=410)
"""

from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import Mapping
from datetime import timedelta
from urllib.parse import urlencode


class InvalidSignatureError(Exception):
    """Raised when a signed URL's HMAC does not match the canonical payload."""


class ExpiredSignatureError(Exception):
    """Raised when a signed URL's ``expires`` timestamp is in the past."""


class MissingSignatureError(Exception):
    """Raised when the ``signature`` query parameter is absent."""


InvalidSignature = InvalidSignatureError
ExpiredSignature = ExpiredSignatureError
MissingSignature = MissingSignatureError


class UrlSigner:
    """Build and verify HMAC-signed URLs.

    The signer is stateless and idempotent. Bind it as a singleton in
    an :class:`AuthServiceProvider` (or any provider) and inject it
    through the container; tests can instantiate it directly with a
    fixed key.

    The canonical form that gets signed is::

        <path>?<sorted urlencoded params including expires>

    Two fields are framework-managed:

    * ``expires`` — integer unix timestamp, present when
      ``expires_in`` was passed to :meth:`sign`.
    * ``signature`` — the hex HMAC-SHA256 digest.
    """

    def __init__(self, key: str | bytes) -> None:
        self._key = key.encode() if isinstance(key, str) else key

    # ------------------------------------------------------------- sign

    def sign(
        self,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        expires_in: timedelta | None = None,
    ) -> str:
        payload = dict(params or {})
        if expires_in is not None:
            payload["expires"] = str(int(time.time() + expires_in.total_seconds()))

        signature = self._compute_signature(path, payload)
        payload["signature"] = signature
        return f"{path}?{urlencode(sorted(payload.items()))}"

    # ----------------------------------------------------------- verify

    def verify(
        self,
        path: str,
        query: Mapping[str, str],
    ) -> dict[str, str]:
        """Validate the signature and expiry on *query*, return the payload.

        The returned dict is the caller-supplied params without the
        framework-managed ``expires`` / ``signature`` fields.
        """
        signature = query.get("signature")
        if not signature:
            raise MissingSignature("signature parameter is missing")

        payload = {k: v for k, v in query.items() if k != "signature"}
        expected = self._compute_signature(path, payload)
        if not hmac.compare_digest(signature, expected):
            raise InvalidSignature("signature mismatch — link tampered or key rotated")

        expires_raw = payload.get("expires")
        if expires_raw is not None:
            try:
                expires = int(expires_raw)
            except ValueError as exc:
                raise InvalidSignature("expires is not a valid timestamp") from exc
            if time.time() > expires:
                raise ExpiredSignature("link expired")

        return {k: v for k, v in payload.items() if k != "expires"}

    # ------------------------------------------------------- internals

    def _compute_signature(
        self, path: str, payload: Mapping[str, str],
    ) -> str:
        canonical = f"{path}?{urlencode(sorted(payload.items()))}"
        return hmac.new(
            self._key, canonical.encode(), hashlib.sha256,
        ).hexdigest()
