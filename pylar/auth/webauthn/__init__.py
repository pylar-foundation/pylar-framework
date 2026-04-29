"""WebAuthn / passkeys support (ADR-0013, phase 15a).

Public surface:

* :class:`WebauthnConfig` — runtime config (``rp_id``, ``rp_name``,
  attestation policy, UV policy, challenge TTL).
* :class:`WebauthnServer` — the service class apps inject into
  controllers. Four async methods: ``make_registration_options`` /
  ``verify_registration`` and ``make_authentication_options`` /
  ``verify_authentication``.
* :class:`WebauthnCredential` — the SA-mapped credential row.
* Exception hierarchy rooted at :class:`WebauthnError`.

Install via ``pylar[webauthn]`` — pulls in ``py_webauthn>=2.0,<3``
and its small transitive graph (``cryptography``, ``cbor2``).
"""

from __future__ import annotations

from pylar.auth.webauthn.attestation import (
    AttestationNotAllowedError,
    AttestationVerifier,
    MetadataServiceAttestationVerifier,
    TrustAnyAttestationVerifier,
)
from pylar.auth.webauthn.config import (
    AttestationConveyance,
    UserVerification,
    WebauthnConfig,
)
from pylar.auth.webauthn.exceptions import (
    WebauthnChallengeExpiredError,
    WebauthnCredentialNotFoundError,
    WebauthnError,
    WebauthnVerificationError,
)
from pylar.auth.webauthn.model import WebauthnCredential
from pylar.auth.webauthn.provider import WebauthnServiceProvider
from pylar.auth.webauthn.server import WebauthnServer

__all__ = [
    "AttestationConveyance",
    "AttestationNotAllowedError",
    "AttestationVerifier",
    "MetadataServiceAttestationVerifier",
    "TrustAnyAttestationVerifier",
    "UserVerification",
    "WebauthnChallengeExpiredError",
    "WebauthnConfig",
    "WebauthnCredential",
    "WebauthnCredentialNotFoundError",
    "WebauthnError",
    "WebauthnServer",
    "WebauthnServiceProvider",
    "WebauthnVerificationError",
]
