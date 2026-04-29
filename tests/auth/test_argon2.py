"""Tests for the optional :class:`Argon2PasswordHasher`."""

from __future__ import annotations

import pytest

from pylar.auth import Argon2PasswordHasher, PasswordHasher

pytest.importorskip("argon2", reason="argon2-cffi not installed (pylar[auth] extra)")


def test_hash_uses_argon2id_phc_format() -> None:
    hasher = Argon2PasswordHasher()
    encoded = hasher.hash("hunter2")
    assert encoded.startswith("$argon2id$")


def test_verify_accepts_correct_password() -> None:
    hasher = Argon2PasswordHasher()
    encoded = hasher.hash("hunter2")
    assert hasher.verify("hunter2", encoded) is True


def test_verify_rejects_wrong_password() -> None:
    hasher = Argon2PasswordHasher()
    encoded = hasher.hash("hunter2")
    assert hasher.verify("hunter3", encoded) is False


def test_verify_rejects_unrelated_string() -> None:
    hasher = Argon2PasswordHasher()
    assert hasher.verify("anything", "not a hash") is False


def test_verify_rejects_other_algorithm_format() -> None:
    hasher = Argon2PasswordHasher()
    pbkdf2_hash = "pbkdf2_sha256$600000$abc$def"
    assert hasher.verify("anything", pbkdf2_hash) is False


def test_two_hashes_of_same_password_differ() -> None:
    hasher = Argon2PasswordHasher()
    a = hasher.hash("same")
    b = hasher.hash("same")
    assert a != b


def test_satisfies_password_hasher_protocol() -> None:
    hasher: PasswordHasher = Argon2PasswordHasher()
    assert isinstance(hasher, PasswordHasher)


def test_needs_rehash_returns_bool() -> None:
    hasher = Argon2PasswordHasher()
    encoded = hasher.hash("x")
    assert hasher.needs_rehash(encoded) is False


def test_constructor_accepts_custom_parameters() -> None:
    hasher = Argon2PasswordHasher(time_cost=3, memory_cost=8192, parallelism=2)
    encoded = hasher.hash("custom")
    assert hasher.verify("custom", encoded)
