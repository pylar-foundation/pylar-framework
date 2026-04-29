"""RFC 6238 time-based OTP + recovery codes (ADR-0009 phase 11d).

Stdlib-only implementation of the algorithm Google Authenticator, Authy,
1Password, and Bitwarden all understand. The module exposes four
primitives and a pair of recovery-code helpers:

* :func:`generate_secret` — fresh base32 secret suitable for storing
  on the user row and rendering into an authenticator-app QR code.
* :func:`provisioning_uri` — the ``otpauth://totp/...`` URI that
  the QR image encodes. Apps render it via any QR library (qrcode,
  segno) — pylar does not ship a QR renderer in core.
* :func:`current_code` — the code an authenticator app would show at
  *now*. Used by tests + CLI flows.
* :func:`verify` — constant-time comparison against the codes valid
  at the current counter ±1, so a 30-second window on both sides of
  the clock tick absorbs typical drift.
* :func:`generate_recovery_codes` + :func:`hash_recovery_code` +
  :func:`verify_recovery_code` — 8 single-use 10-char recovery codes
  minted at enrolment. Apps store the hashes; a verified match is
  consumed so the code can't be reused.

No new dependencies — the whole file is ~150 lines of stdlib.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from collections.abc import Iterable
from urllib.parse import quote, urlencode

#: Default TOTP step (seconds between code rotations). RFC 6238
#: recommends 30; authenticator apps hard-code it; apps that need a
#: different step are already off the golden path.
_STEP = 30

#: Default code length — every mainstream authenticator shows 6.
_DIGITS = 6

#: Base32 secret length in bytes (before base32 encoding). 20 bytes
#: → 32 chars of base32, which matches every authenticator's
#: "enter secret manually" UI.
_SECRET_BYTES = 20

#: Human-readable recovery codes. 10 alphanumerics gives ~52 bits of
#: entropy per code — well above what an attacker can brute-force
#: inside the 8 chances a user has.
_RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I
_RECOVERY_LENGTH = 10
_RECOVERY_COUNT = 8


# ------------------------------------------------------------- TOTP core


def generate_secret() -> str:
    """Return a fresh base32-encoded 20-byte secret.

    Store the string on the user row — the provisioning URI and the
    `verify` call both accept it directly without extra parsing.
    """
    raw = secrets.token_bytes(_SECRET_BYTES)
    return base64.b32encode(raw).decode("ascii").rstrip("=")


def provisioning_uri(
    *,
    account_name: str,
    secret: str,
    issuer: str,
    digits: int = _DIGITS,
    period: int = _STEP,
) -> str:
    """Build the ``otpauth://totp/…`` URI for QR enrolment.

    ``account_name`` is typically the user's email; ``issuer`` is the
    application name displayed in the authenticator app alongside the
    entry. Both are URL-encoded before being dropped into the URI.
    """
    label = f"{quote(issuer, safe='')}:{quote(account_name, safe='')}"
    query = urlencode({
        "secret": secret,
        "issuer": issuer,
        "digits": str(digits),
        "period": str(period),
        "algorithm": "SHA1",
    })
    return f"otpauth://totp/{label}?{query}"


def current_code(
    secret: str,
    *,
    now: float | None = None,
    digits: int = _DIGITS,
    step: int = _STEP,
) -> str:
    """Return the TOTP code an authenticator app would show at *now*.

    *now* defaults to ``time.time()``. Tests pin it to a fixed moment
    to exercise drift-window behaviour deterministically.
    """
    counter = int((now if now is not None else time.time()) // step)
    return _hotp(secret, counter, digits=digits)


def verify(
    secret: str,
    code: str,
    *,
    now: float | None = None,
    window: int = 1,
    digits: int = _DIGITS,
    step: int = _STEP,
) -> bool:
    """Constant-time check of *code* against the valid codes at now ± window.

    Returns ``True`` when the candidate matches the code at the
    current counter or any neighbouring step inside *window*. Default
    window = 1 ⇒ the code before, the current, and the next; apps
    that need tighter tolerance pass ``window=0``.
    """
    if not code or not code.isdigit() or len(code) != digits:
        return False
    counter = int((now if now is not None else time.time()) // step)
    for delta in range(-window, window + 1):
        expected = _hotp(secret, counter + delta, digits=digits)
        if hmac.compare_digest(expected, code):
            return True
    return False


def _hotp(secret: str, counter: int, *, digits: int) -> str:
    """RFC 4226 HOTP — the piece both HOTP and TOTP share.

    Decodes the base32 secret, HMAC-SHA1s the 8-byte big-endian
    counter, performs the dynamic truncation the spec prescribes,
    and returns the last *digits* decimal digits as a zero-padded
    string.
    """
    key = base64.b32decode(_pad_b32(secret))
    payload = struct.pack(">Q", counter)
    digest = hmac.new(key, payload, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    truncated = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFF_FFFF
    return str(truncated % (10 ** digits)).zfill(digits)


def _pad_b32(secret: str) -> str:
    """Restore the ``=`` padding that :func:`generate_secret` stripped."""
    return secret + "=" * (-len(secret) % 8)


# ------------------------------------------------------------ recovery codes


def generate_recovery_codes(count: int = _RECOVERY_COUNT) -> list[str]:
    """Mint *count* single-use recovery codes of the form ``ABCDE-FGHJK``.

    The dash is cosmetic — :func:`verify_recovery_code` normalises
    on both sides so users can enter the code with or without it.
    """
    codes: list[str] = []
    for _ in range(count):
        chars = "".join(
            secrets.choice(_RECOVERY_ALPHABET) for _ in range(_RECOVERY_LENGTH)
        )
        # Split halfway for readability.
        codes.append(f"{chars[:5]}-{chars[5:]}")
    return codes


def hash_recovery_code(code: str) -> str:
    """Hex SHA-256 of the normalised code — same shape as API-token hashes."""
    return hashlib.sha256(_normalise_recovery(code).encode()).hexdigest()


def verify_recovery_code(
    candidate: str,
    stored_hashes: Iterable[str],
) -> str | None:
    """Return the matched hash from *stored_hashes*, or ``None``.

    Pattern: the caller passes the list of remaining hashed codes for
    the user; on a hit, the match is removed from storage so the code
    can't be reused. The verify helper stays pure — persistence is
    the caller's responsibility::

        matched = verify_recovery_code(entered, user.recovery_codes)
        if matched:
            user.recovery_codes.remove(matched)
            await user.save()
    """
    target = hash_recovery_code(candidate)
    for stored in stored_hashes:
        if hmac.compare_digest(stored, target):
            return stored
    return None


def _normalise_recovery(code: str) -> str:
    """Strip whitespace + dashes, upper-case, for forgiving user input."""
    return "".join(ch for ch in code.upper() if ch.isalnum())
