"""Attestation verification pluggables for WebAuthn (ADR-0013 phase 15d).

WebAuthn attestation lets a relying party verify *which authenticator
model* produced a credential by checking the attestation certificate
chain against a trusted root. The default posture across the modern
ecosystem is ``attestation="none"`` — no chain check — because passkey
adoption across consumer browsers outgrew the enterprise-only model
of caring about specific device certifications. Pylar honours that
default.

For regulated or high-assurance deployments that *do* need model-level
attestation (e.g. "only FIPS 140-2 Level 2 authenticators",
"reject anything flagged compromised by FIDO MDS"), this module
introduces an :class:`AttestationVerifier` pluggable. Apps bind a
verifier in their container; :class:`WebauthnServer` consults it
during registration to (a) receive the list of trust roots per
attestation format and (b) get a final yes/no on the AAGUID after
py_webauthn has cryptographically validated the assertion.

Pylar ships two implementations:

* :class:`TrustAnyAttestationVerifier` — the default. Returns no
  roots (py_webauthn then skips chain verification) and accepts any
  AAGUID. Equivalent to the behaviour before this phase shipped.
* :class:`MetadataServiceAttestationVerifier` — loads a pre-fetched
  FIDO MDS3 JSON blob from disk, indexes entries by AAGUID, and
  surfaces both the trust roots and a per-authenticator policy hook
  that rejects revoked / compromised devices.

Automatic download and JWT verification of the MDS blob are
deliberately out of scope for v1 — operators fetch the blob on their
own schedule and verify it against the FIDO Alliance root using
standard JWT tooling. A future ADR can fold the download into the
framework if demand appears.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol, runtime_checkable
from uuid import UUID

from pylar.auth.webauthn.exceptions import WebauthnVerificationError


class AttestationNotAllowedError(WebauthnVerificationError):
    """Raised when a verifier rejects the attested authenticator.

    Separate from the generic ``WebauthnVerificationError`` so policy
    logs and ops dashboards can distinguish "the crypto was fine but
    we don't trust this device model" from "the signature didn't
    check out".
    """


@runtime_checkable
class AttestationVerifier(Protocol):
    """Policy pluggable consulted during WebAuthn registration.

    One instance is bound in the container; :class:`WebauthnServer`
    pulls it at construction time. The protocol has two methods
    because the verification lifecycle has two concerns —
    cryptographic chain validation (which ``py_webauthn`` handles,
    given the right roots) and policy-level accept/reject (which is
    always application-specific).
    """

    async def roots_for(self, attestation_format: str) -> list[bytes]:
        """Return PEM-encoded trust-root certs for the given format.

        *attestation_format* is one of ``"packed"``, ``"tpm"``,
        ``"android-key"``, ``"android-safetynet"``, ``"fido-u2f"``,
        ``"apple"``, or ``"none"``. Implementations may return an
        empty list to signal "don't verify the chain for this
        format" — useful for dev environments and for the default
        "accept anything" verifier.
        """
        ...

    async def check_authenticator(
        self,
        aaguid: UUID | None,
        *,
        attestation_format: str,
    ) -> None:
        """Inspect the AAGUID after ``py_webauthn`` has accepted the chain.

        Raise :class:`AttestationNotAllowedError` to reject the
        registration. Called once per successful registration
        ceremony, *after* chain verification succeeded. Implementations
        typically consult a metadata blob to check status flags
        (``REVOKED``, ``USER_VERIFICATION_BYPASS``, etc).
        """
        ...


class TrustAnyAttestationVerifier:
    """Default verifier — no roots, no AAGUID checks.

    Kept as the default so apps that install ``pylar[webauthn]``
    without thinking about attestation get the ecosystem-standard
    ``attestation="none"`` behaviour. Swap in
    :class:`MetadataServiceAttestationVerifier` when an operator
    explicitly wants model-level trust decisions.
    """

    async def roots_for(self, attestation_format: str) -> list[bytes]:
        return []

    async def check_authenticator(
        self,
        aaguid: UUID | None,
        *,
        attestation_format: str,
    ) -> None:
        return None


class MetadataServiceAttestationVerifier:
    """Load a FIDO MDS3 JSON blob from disk and use it for policy decisions.

    The MDS blob is the FIDO Alliance's signed manifest of every
    certified authenticator, keyed by AAGUID, carrying the trust-root
    certs and status reports. The blob is distributed as a JWT at
    ``https://mds3.fidoalliance.org/`` — operators download and verify
    it themselves (standard JWT validation against the FIDO root),
    then pass the decoded JSON to this verifier.

    *metadata_path* points to either the raw parsed JSON (the common
    case) or a file containing the same. The decoded structure is the
    MDS3 "blobPayload" object — i.e. ``{"entries": [{"aaguid": ...,
    "metadataStatement": ..., "statusReports": [...]}, ...]}``.

    *blocked_status_codes* is the set of ``AuthenticatorStatus`` values
    that should cause a registration to be rejected. Defaults cover
    the revoked / attack-compromised set; operators tighten or
    loosen to match their policy.
    """

    #: Authenticator status codes that FIDO tags as actively dangerous.
    #: Registrations against authenticators currently carrying any of
    #: these statuses are rejected by default. Status strings come
    #: from the ``AuthenticatorStatus`` enum in the FIDO MDS spec.
    _DEFAULT_BLOCKED_STATUSES: frozenset[str] = frozenset({
        "REVOKED",
        "USER_VERIFICATION_BYPASS",
        "ATTESTATION_KEY_COMPROMISE",
        "USER_KEY_REMOTE_COMPROMISE",
        "USER_KEY_PHYSICAL_COMPROMISE",
    })

    def __init__(
        self,
        metadata: dict[str, object] | None = None,
        *,
        metadata_path: Path | str | None = None,
        blocked_status_codes: frozenset[str] | None = None,
    ) -> None:
        if metadata is None and metadata_path is None:
            raise ValueError(
                "Pass either metadata=<dict> or metadata_path=<Path> "
                "to MetadataServiceAttestationVerifier."
            )
        if metadata_path is not None:
            path = Path(metadata_path)
            metadata = json.loads(path.read_text(encoding="utf-8"))
        assert metadata is not None  # narrow for mypy
        self._blocked = blocked_status_codes or self._DEFAULT_BLOCKED_STATUSES
        self._by_aaguid, self._roots_by_fmt = self._index(metadata)

    @staticmethod
    def _index(
        metadata: dict[str, object],
    ) -> tuple[dict[UUID, dict[str, object]], dict[str, list[bytes]]]:
        """Walk the MDS entries once and build two fast lookup maps.

        ``by_aaguid`` feeds the per-registration status check.
        ``roots_by_fmt`` feeds ``py_webauthn`` at verification time.
        """
        entries = metadata.get("entries", [])
        if not isinstance(entries, list):
            entries = []

        by_aaguid: dict[UUID, dict[str, object]] = {}
        roots_by_fmt: dict[str, list[bytes]] = {}
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            raw_aaguid = entry.get("aaguid")
            if isinstance(raw_aaguid, str):
                try:
                    by_aaguid[UUID(raw_aaguid)] = entry
                except ValueError:
                    continue
            statement = entry.get("metadataStatement")
            if not isinstance(statement, dict):
                continue
            fmts = statement.get("attestationTypes")
            if isinstance(fmts, str):
                fmts = [fmts]
            if not isinstance(fmts, list):
                fmts = []
            roots = statement.get("attestationRootCertificates")
            if not isinstance(roots, list):
                continue
            pem_blobs = [_b64_to_pem(r) for r in roots if isinstance(r, str)]
            for raw_fmt in fmts:
                if not isinstance(raw_fmt, str):
                    continue
                # MDS uses the attestation-type enum, which overlaps
                # with the WebAuthn format enum for the values we
                # care about (``packed``, ``tpm``, ``fido-u2f``, etc).
                roots_by_fmt.setdefault(raw_fmt, []).extend(pem_blobs)
        return by_aaguid, roots_by_fmt

    async def roots_for(self, attestation_format: str) -> list[bytes]:
        return list(self._roots_by_fmt.get(attestation_format, []))

    async def check_authenticator(
        self,
        aaguid: UUID | None,
        *,
        attestation_format: str,
    ) -> None:
        if aaguid is None:
            # No AAGUID means the authenticator declined to identify
            # itself (common for FIDO U2F devices). MDS can't decide;
            # fall back to allowing — chain verification already
            # accepted the key.
            return None
        entry = self._by_aaguid.get(aaguid)
        if entry is None:
            raise AttestationNotAllowedError(
                f"AAGUID {aaguid} is not present in the metadata service — "
                f"authenticator is not certified or the MDS blob is stale."
            )
        reports = entry.get("statusReports")
        if not isinstance(reports, list):
            return None
        for report in reports:
            if not isinstance(report, dict):
                continue
            status = report.get("status")
            if isinstance(status, str) and status in self._blocked:
                raise AttestationNotAllowedError(
                    f"AAGUID {aaguid} has blocked status {status!r} per MDS."
                )
        return None


def _b64_to_pem(value: str) -> bytes:
    """Turn an MDS-distributed base64 DER cert into a PEM blob.

    FIDO MDS ships attestation root certs as raw base64-encoded DER.
    ``py_webauthn`` expects PEM. Wrap the body with the
    ``BEGIN/END CERTIFICATE`` guards and normalise line length to 64
    chars so OpenSSL can decode it.
    """
    body = "".join(value.split())  # strip whitespace just in case
    wrapped = "\n".join(body[i:i + 64] for i in range(0, len(body), 64))
    return (
        b"-----BEGIN CERTIFICATE-----\n"
        + wrapped.encode("ascii")
        + b"\n-----END CERTIFICATE-----\n"
    )
