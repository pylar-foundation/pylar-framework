"""WebAuthn-specific exceptions (ADR-0013 phase 15a)."""

from __future__ import annotations

from pylar.auth.exceptions import AuthError


class WebauthnError(AuthError):
    """Base class for every WebAuthn failure.

    Applications catch this single class to distinguish WebAuthn
    failures from other auth errors without needing to know which
    sub-reason triggered the rejection. Sub-classes exist for
    logging / metrics scopes, not for control flow.
    """


class WebauthnVerificationError(WebauthnError):
    """Raised when `py_webauthn` rejects the browser response.

    Wraps the library's internal errors (bad signature, origin
    mismatch, RP ID mismatch, malformed attestation, sign-count
    regression) so callers catch one exception regardless of the
    spec-level failure mode.
    """


class WebauthnChallengeExpiredError(WebauthnError):
    """Raised when the stored ceremony challenge has expired or is missing.

    The default TTL is 5 minutes (``WebauthnConfig.challenge_ttl_seconds``).
    Clients that take longer to complete the ceremony must restart it
    by calling ``make_registration_options`` / ``make_authentication_options``
    again.
    """


class WebauthnCredentialNotFoundError(WebauthnError):
    """Raised when a credential ID from the browser is not on file.

    Happens for stale credentials the user revoked, or for an
    assertion coming from a different RP with a colliding credential
    ID. Callers should treat this the same as a failed password
    attempt — log, throttle, surface a generic error to the client.
    """
