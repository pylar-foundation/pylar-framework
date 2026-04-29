"""Tests for the AttestationVerifier pluggables (ADR-0013 phase 15d)."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from uuid import UUID

import pytest

from pylar.auth.webauthn import (
    AttestationNotAllowedError,
    MetadataServiceAttestationVerifier,
    TrustAnyAttestationVerifier,
)

# -------------------------------------------------- TrustAny


async def test_trust_any_returns_no_roots() -> None:
    verifier = TrustAnyAttestationVerifier()
    assert await verifier.roots_for("packed") == []
    assert await verifier.roots_for("tpm") == []


async def test_trust_any_accepts_every_aaguid() -> None:
    verifier = TrustAnyAttestationVerifier()
    # None (missing AAGUID) and random UUIDs all pass.
    await verifier.check_authenticator(None, attestation_format="packed")
    await verifier.check_authenticator(
        UUID("00000000-0000-0000-0000-000000000001"),
        attestation_format="packed",
    )


# -------------------------------------------------- MDS verifier


_AAGUID_OK = UUID("11111111-1111-1111-1111-111111111111")
_AAGUID_REVOKED = UUID("22222222-2222-2222-2222-222222222222")
_AAGUID_UNKNOWN = UUID("99999999-9999-9999-9999-999999999999")


def _fake_cert(marker: str) -> str:
    """Return a base64-encoded fake DER blob containing *marker* verbatim.

    The tests only care about plumbing; the verifier doesn't inspect
    certificate contents, it hands them straight through to
    ``py_webauthn`` which expects PEM format. We just make sure the
    value survives the round-trip.
    """
    return base64.b64encode(marker.encode("ascii")).decode("ascii")


def _build_mds(tmp_path: Path) -> Path:
    blob = {
        "entries": [
            {
                "aaguid": str(_AAGUID_OK),
                "metadataStatement": {
                    "attestationTypes": ["packed"],
                    "attestationRootCertificates": [
                        _fake_cert("root-ok-1"),
                        _fake_cert("root-ok-2"),
                    ],
                },
                "statusReports": [
                    {"status": "FIDO_CERTIFIED_L1"},
                ],
            },
            {
                "aaguid": str(_AAGUID_REVOKED),
                "metadataStatement": {
                    "attestationTypes": ["tpm"],
                    "attestationRootCertificates": [_fake_cert("root-revoked")],
                },
                "statusReports": [
                    {"status": "REVOKED"},
                ],
            },
        ],
    }
    path = tmp_path / "mds.json"
    path.write_text(json.dumps(blob), encoding="utf-8")
    return path


def test_constructor_requires_metadata_source() -> None:
    with pytest.raises(ValueError, match="metadata="):
        MetadataServiceAttestationVerifier()


def test_constructor_accepts_dict_directly() -> None:
    verifier = MetadataServiceAttestationVerifier(metadata={"entries": []})
    assert verifier is not None


def test_constructor_loads_from_path(tmp_path: Path) -> None:
    path = _build_mds(tmp_path)
    verifier = MetadataServiceAttestationVerifier(metadata_path=path)
    assert verifier is not None


async def test_roots_for_wraps_der_into_pem(tmp_path: Path) -> None:
    verifier = MetadataServiceAttestationVerifier(metadata_path=_build_mds(tmp_path))
    roots = await verifier.roots_for("packed")
    assert len(roots) == 2
    for pem in roots:
        assert pem.startswith(b"-----BEGIN CERTIFICATE-----")
        assert pem.endswith(b"-----END CERTIFICATE-----\n")


async def test_roots_for_empty_format_returns_empty(tmp_path: Path) -> None:
    verifier = MetadataServiceAttestationVerifier(metadata_path=_build_mds(tmp_path))
    assert await verifier.roots_for("apple") == []


async def test_check_authenticator_allows_certified(tmp_path: Path) -> None:
    verifier = MetadataServiceAttestationVerifier(metadata_path=_build_mds(tmp_path))
    await verifier.check_authenticator(
        _AAGUID_OK, attestation_format="packed",
    )  # Does not raise.


async def test_check_authenticator_rejects_revoked(tmp_path: Path) -> None:
    verifier = MetadataServiceAttestationVerifier(metadata_path=_build_mds(tmp_path))
    with pytest.raises(AttestationNotAllowedError, match="REVOKED"):
        await verifier.check_authenticator(
            _AAGUID_REVOKED, attestation_format="tpm",
        )


async def test_check_authenticator_rejects_unknown_aaguid(tmp_path: Path) -> None:
    verifier = MetadataServiceAttestationVerifier(metadata_path=_build_mds(tmp_path))
    with pytest.raises(AttestationNotAllowedError, match="not present"):
        await verifier.check_authenticator(
            _AAGUID_UNKNOWN, attestation_format="packed",
        )


async def test_check_authenticator_allows_missing_aaguid(tmp_path: Path) -> None:
    """U2F devices don't report an AAGUID — verifier must not reject that."""
    verifier = MetadataServiceAttestationVerifier(metadata_path=_build_mds(tmp_path))
    await verifier.check_authenticator(None, attestation_format="fido-u2f")


async def test_custom_blocked_status_set() -> None:
    """Operators can tighten the blocked set beyond the defaults."""
    metadata = {
        "entries": [
            {
                "aaguid": str(_AAGUID_OK),
                "metadataStatement": {"attestationTypes": ["packed"]},
                "statusReports": [
                    {"status": "NOT_FIDO_CERTIFIED"},
                ],
            },
        ],
    }
    verifier = MetadataServiceAttestationVerifier(
        metadata=metadata,
        blocked_status_codes=frozenset({"NOT_FIDO_CERTIFIED"}),
    )
    with pytest.raises(AttestationNotAllowedError, match="NOT_FIDO_CERTIFIED"):
        await verifier.check_authenticator(
            _AAGUID_OK, attestation_format="packed",
        )
