"""Behavioural tests for :class:`Pbkdf2PasswordHasher`."""

from __future__ import annotations

import pytest

from pylar.auth import PasswordHasher, Pbkdf2PasswordHasher


def test_hash_uses_documented_format() -> None:
    hasher = Pbkdf2PasswordHasher(iterations=200_000)
    encoded = hasher.hash("hunter2")
    parts = encoded.split("$")
    assert len(parts) == 4
    assert parts[0] == "pbkdf2_sha256"
    assert parts[1] == "200000"
    assert len(parts[2]) == 32  # 16 bytes hex-encoded


def test_verify_accepts_correct_password() -> None:
    hasher = Pbkdf2PasswordHasher(iterations=200_000)
    encoded = hasher.hash("hunter2")
    assert hasher.verify("hunter2", encoded) is True


def test_verify_rejects_wrong_password() -> None:
    hasher = Pbkdf2PasswordHasher(iterations=200_000)
    encoded = hasher.hash("hunter2")
    assert hasher.verify("hunter3", encoded) is False


def test_two_hashes_of_same_password_use_different_salts() -> None:
    hasher = Pbkdf2PasswordHasher(iterations=200_000)
    a = hasher.hash("same")
    b = hasher.hash("same")
    assert a != b
    assert hasher.verify("same", a)
    assert hasher.verify("same", b)


def test_verify_rejects_unknown_algorithm() -> None:
    hasher = Pbkdf2PasswordHasher(iterations=200_000)
    assert hasher.verify("x", "scrypt$1$salt$hash") is False


def test_verify_rejects_malformed_hash() -> None:
    hasher = Pbkdf2PasswordHasher(iterations=200_000)
    assert hasher.verify("x", "not a hash") is False
    assert hasher.verify("x", "pbkdf2_sha256$abc$salt$hash") is False  # bad iterations


def test_constructor_rejects_too_few_iterations() -> None:
    with pytest.raises(ValueError, match="100,000"):
        Pbkdf2PasswordHasher(iterations=50_000)


def test_protocol_is_runtime_checkable() -> None:
    hasher: PasswordHasher = Pbkdf2PasswordHasher(iterations=200_000)
    assert isinstance(hasher, PasswordHasher)
