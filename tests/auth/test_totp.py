"""Tests for TOTP + recovery codes (ADR-0009 phase 11d).

The TOTP tests exercise the algorithm against the RFC 6238 reference
test vectors so correctness is verifiable against an external
authority, not just round-tripped through our own code.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlparse

import pytest

from pylar.auth.totp import (
    current_code,
    generate_recovery_codes,
    generate_secret,
    hash_recovery_code,
    provisioning_uri,
    verify,
    verify_recovery_code,
)

# --------------------------------------------------- secret + provisioning


def test_generate_secret_has_expected_base32_shape() -> None:
    secret = generate_secret()
    # 20 bytes → 32 base32 chars with no padding.
    assert len(secret) == 32
    assert secret == secret.upper()
    assert set(secret) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")


def test_generate_secret_is_unique_across_calls() -> None:
    assert generate_secret() != generate_secret()


def test_provisioning_uri_encodes_label_and_query() -> None:
    uri = provisioning_uri(
        account_name="alice@example.com",
        secret="JBSWY3DPEHPK3PXP",
        issuer="Pylar Demo",
    )
    parsed = urlparse(uri)
    assert parsed.scheme == "otpauth"
    assert parsed.netloc == "totp"
    # Label is issuer:account, both URL-encoded.
    assert parsed.path.startswith("/Pylar%20Demo:alice%40example.com")
    query = dict(parse_qsl(parsed.query))
    assert query["secret"] == "JBSWY3DPEHPK3PXP"
    assert query["issuer"] == "Pylar Demo"
    assert query["digits"] == "6"
    assert query["period"] == "30"
    assert query["algorithm"] == "SHA1"


# ---------------------------------------------------- RFC 6238 test vectors


# Per RFC 6238 §Appendix B — SHA-1 vectors, 8-digit codes. The shared
# ASCII secret is "12345678901234567890"; base32-encoded for this test.
_RFC_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"

_RFC_VECTORS = [
    (59, "94287082"),
    (1111111109, "07081804"),
    (1111111111, "14050471"),
    (1234567890, "89005924"),
    (2000000000, "69279037"),
    (20000000000, "65353130"),
]


@pytest.mark.parametrize("epoch,expected", _RFC_VECTORS)
def test_current_code_matches_rfc_6238_vectors(epoch: int, expected: str) -> None:
    """TOTP at each RFC 6238 timestamp produces the published 8-digit code."""
    assert current_code(_RFC_SECRET, now=epoch, digits=8) == expected


def test_verify_accepts_current_code() -> None:
    secret = generate_secret()
    now = 1700_000_000.0
    code = current_code(secret, now=now)
    assert verify(secret, code, now=now) is True


def test_verify_accepts_code_from_previous_window() -> None:
    """A code from 30 s ago is still valid with the default ±1 window."""
    secret = generate_secret()
    now = 1700_000_000.0
    code = current_code(secret, now=now - 30)
    assert verify(secret, code, now=now) is True


def test_verify_rejects_code_two_windows_ago() -> None:
    """±1 window = 90 s total acceptance; 60 s drift is outside."""
    secret = generate_secret()
    now = 1700_000_000.0
    code = current_code(secret, now=now - 60)
    assert verify(secret, code, now=now) is False


def test_verify_rejects_malformed_input() -> None:
    secret = generate_secret()
    assert verify(secret, "", now=0) is False
    assert verify(secret, "abcdef", now=0) is False  # non-digit
    assert verify(secret, "123", now=0) is False  # wrong length


# ------------------------------------------------------- recovery codes


def test_generate_recovery_codes_count_and_shape() -> None:
    codes = generate_recovery_codes()
    assert len(codes) == 8
    for code in codes:
        assert len(code) == 11  # 5 + dash + 5
        assert code[5] == "-"
        alnum = code.replace("-", "")
        assert alnum.isalnum()
        assert alnum == alnum.upper()
        # Confusable chars are excluded.
        assert not set(alnum) & {"0", "O", "1", "I"}


def test_generate_recovery_codes_respects_count_argument() -> None:
    assert len(generate_recovery_codes(count=3)) == 3


def test_recovery_round_trip_accepts_dash_and_case() -> None:
    codes = generate_recovery_codes()
    stored = [hash_recovery_code(c) for c in codes]
    picked = codes[2]
    # Exact match.
    assert verify_recovery_code(picked, stored) is not None
    # Lowercase + extra whitespace user input.
    assert verify_recovery_code(
        f"  {picked.lower().replace('-', '')}  ", stored,
    ) is not None


def test_recovery_mismatch_returns_none() -> None:
    stored = [hash_recovery_code(c) for c in generate_recovery_codes()]
    assert verify_recovery_code("NEVER-MATCH", stored) is None


def test_recovery_matched_hash_is_removable_by_caller() -> None:
    """The caller uses the return value to consume the used code."""
    codes = generate_recovery_codes(count=3)
    stored = [hash_recovery_code(c) for c in codes]

    match = verify_recovery_code(codes[0], stored)
    assert match is not None
    stored.remove(match)
    # Replaying the consumed code after removal fails.
    assert verify_recovery_code(codes[0], stored) is None
    # Other codes still work.
    assert verify_recovery_code(codes[1], stored) is not None
