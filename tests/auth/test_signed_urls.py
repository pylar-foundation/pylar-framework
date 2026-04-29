"""Tests for UrlSigner — HMAC-signed URLs (ADR-0009 phase 11a)."""

from __future__ import annotations

import time
from datetime import timedelta
from urllib.parse import parse_qsl, urlparse

import pytest

from pylar.auth import (
    ExpiredSignature,
    InvalidSignature,
    MissingSignature,
    UrlSigner,
)


def _parse_qs(url: str) -> dict[str, str]:
    return dict(parse_qsl(urlparse(url).query, keep_blank_values=True))


def test_sign_appends_signature_parameter() -> None:
    signer = UrlSigner("test-key-123")
    url = signer.sign("/verify", params={"user_id": "42"})
    query = _parse_qs(url)
    assert query["user_id"] == "42"
    assert "signature" in query


def test_sign_includes_expires_when_requested() -> None:
    signer = UrlSigner("k")
    url = signer.sign(
        "/verify", params={"user_id": "1"}, expires_in=timedelta(hours=1),
    )
    query = _parse_qs(url)
    assert "expires" in query
    assert int(query["expires"]) > time.time()


def test_verify_round_trip_returns_params() -> None:
    signer = UrlSigner("k")
    url = signer.sign("/verify", params={"user_id": "7", "scope": "email"})
    query = _parse_qs(url)

    params = signer.verify("/verify", query)
    assert params == {"user_id": "7", "scope": "email"}


def test_verify_raises_on_missing_signature() -> None:
    signer = UrlSigner("k")
    with pytest.raises(MissingSignature):
        signer.verify("/verify", {"user_id": "7"})


def test_verify_detects_tampered_param() -> None:
    signer = UrlSigner("k")
    url = signer.sign("/verify", params={"user_id": "7"})
    query = _parse_qs(url)
    # Flip the user id after signing — the signature no longer matches.
    query["user_id"] = "8"
    with pytest.raises(InvalidSignature):
        signer.verify("/verify", query)


def test_verify_detects_tampered_path() -> None:
    signer = UrlSigner("k")
    url = signer.sign("/verify", params={"user_id": "7"})
    query = _parse_qs(url)
    # Replay on a different path.
    with pytest.raises(InvalidSignature):
        signer.verify("/reset", query)


def test_verify_detects_rotated_key() -> None:
    signer_a = UrlSigner("old-key")
    signer_b = UrlSigner("rotated-key")
    url = signer_a.sign("/verify", params={"user_id": "7"})
    query = _parse_qs(url)
    with pytest.raises(InvalidSignature):
        signer_b.verify("/verify", query)


def test_verify_raises_on_expired_link() -> None:
    signer = UrlSigner("k")
    url = signer.sign(
        "/verify", params={"user_id": "1"},
        expires_in=timedelta(seconds=-1),  # already expired
    )
    query = _parse_qs(url)
    with pytest.raises(ExpiredSignature):
        signer.verify("/verify", query)


def test_verify_honours_unexpired_link() -> None:
    signer = UrlSigner("k")
    url = signer.sign(
        "/verify", params={"user_id": "1"},
        expires_in=timedelta(hours=1),
    )
    query = _parse_qs(url)
    result = signer.verify("/verify", query)
    assert result == {"user_id": "1"}


def test_verify_rejects_malformed_expires() -> None:
    signer = UrlSigner("k")
    # Build the url with garbage expires — re-sign so signature is valid
    # against the garbage, but .verify() still rejects the int parse.
    url = signer.sign("/x", params={"expires": "not-a-number"})
    query = _parse_qs(url)
    with pytest.raises(InvalidSignature):
        signer.verify("/x", query)
