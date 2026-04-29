"""Configuration for the WebAuthn server (ADR-0013 phase 15a).

Bound in the application's ``config/auth.py`` alongside the rest of
the auth stack::

    from pylar.auth import AuthConfig
    from pylar.auth.webauthn import WebauthnConfig

    config = AuthConfig(...)
    webauthn = WebauthnConfig(
        rp_id="example.com",
        rp_name="Example",
    )

``rp_id`` is the security boundary — WebAuthn binds every registered
credential to the exact RP ID that issued it. Moving a deployment
from ``app.example.com`` to ``example.com`` invalidates every
existing passkey, so operators set this value consciously at boot
rather than deriving it per-request.
"""

from __future__ import annotations

from typing import Literal

from pylar.config import BaseConfig

#: User-verification policy passed to the browser. ``"preferred"``
#: matches the ecosystem default — the authenticator asks for UV if
#: it supports it (TouchID / Face ID / PIN) but falls back to mere
#: presence otherwise. Flip to ``"required"`` for step-up or admin
#: flows; ``"discouraged"`` is for low-value cases where a tap is
#: enough.
UserVerification = Literal["required", "preferred", "discouraged"]


#: Attestation policy. ``"none"`` matches GitHub / Google / Microsoft:
#: the server does not inspect the authenticator's certificate chain
#: and accepts any conforming device. ``"direct"`` or ``"indirect"``
#: opt in to verifying the attestation certificate, typically against
#: the FIDO Metadata Service — that integration is deferred to phase
#: 15d of ADR-0013.
AttestationConveyance = Literal["none", "direct", "indirect"]


class WebauthnConfig(BaseConfig):
    """Runtime configuration for :class:`WebauthnServer`.

    Most apps only set ``rp_id`` and ``rp_name``; the rest of the
    fields carry sensible defaults that match the WebAuthn ecosystem
    conventions.
    """

    rp_id: str
    """The relying-party identifier. Must be a registrable domain
    suffix of the site's origin (e.g. ``"example.com"`` for both
    ``https://example.com`` and ``https://admin.example.com``). Set
    to ``"localhost"`` in development."""

    rp_name: str
    """Human-readable relying-party name. Displayed by the browser's
    authenticator UI during registration."""

    origin: str | None = None
    """Expected origin for ceremony responses. ``None`` means the
    server trusts the request's own origin header — the common case.
    Set explicitly only when running behind a reverse proxy that
    rewrites the origin."""

    user_verification: UserVerification = "preferred"
    """Whether the authenticator must verify the user (TouchID / PIN
    / Face ID) during the ceremony. See the ``UserVerification`` alias
    for the tradeoffs."""

    attestation: AttestationConveyance = "none"
    """Attestation conveyance preference. ``"none"`` skips certificate
    verification entirely — matches modern ecosystem practice and
    avoids the FIDO MDS integration burden."""

    require_resident_key: bool = False
    """Request a discoverable (resident-key) credential during
    registration. Set to ``True`` when enrolling passkeys for the
    passwordless-primary flow of phase 15b."""

    challenge_ttl_seconds: int = 300
    """How long a generated ceremony challenge stays valid. The
    WebAuthn spec recommends 5 minutes; users who miss the window
    simply restart the ceremony."""
