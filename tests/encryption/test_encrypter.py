"""Tests for the Encrypter and EncryptedSessionStore."""

from __future__ import annotations

import pytest

from pylar.encryption import DecryptionError, Encrypter, EncryptionError
from pylar.session import MemorySessionStore
from pylar.session.encrypted_store import EncryptedSessionStore

# ----------------------------------------------------------- Encrypter


def _enc() -> Encrypter:
    key = Encrypter.key_from_string(Encrypter.generate_key())
    return Encrypter(key)


def test_encrypt_decrypt_round_trip() -> None:
    enc = _enc()
    token = enc.encrypt(b"hello world")
    assert enc.decrypt(token) == b"hello world"


def test_encrypt_string_round_trip() -> None:
    enc = _enc()
    token = enc.encrypt_string("secret")
    assert enc.decrypt_string(token) == "secret"


def test_different_ciphertext_each_call() -> None:
    enc = _enc()
    a = enc.encrypt(b"same")
    b = enc.encrypt(b"same")
    assert a != b  # fresh nonce each time


def test_wrong_key_raises_decryption_error() -> None:
    enc1 = _enc()
    enc2 = _enc()
    token = enc1.encrypt(b"data")
    with pytest.raises(DecryptionError):
        enc2.decrypt(token)


def test_tampered_token_raises() -> None:
    enc = _enc()
    token = enc.encrypt(b"data")
    tampered = token[:-4] + "XXXX"
    with pytest.raises(DecryptionError):
        enc.decrypt(tampered)


def test_bad_key_length_raises() -> None:
    with pytest.raises(EncryptionError, match="32 bytes"):
        Encrypter(b"too-short")


def test_generate_key_format() -> None:
    key = Encrypter.generate_key()
    assert key.startswith("base64:")
    raw = Encrypter.key_from_string(key)
    assert len(raw) == 32


def test_key_from_string_bare_base64() -> None:
    import base64
    import os
    raw = os.urandom(32)
    b64 = base64.b64encode(raw).decode()
    assert Encrypter.key_from_string(b64) == raw


# ------------------------------------------------------ EncryptedSessionStore


async def test_encrypted_store_round_trip() -> None:
    enc = _enc()
    inner = MemorySessionStore()
    store = EncryptedSessionStore(inner=inner, encrypter=enc)

    await store.write("sid", {"user_id": 42, "role": "admin"}, ttl_seconds=60)

    # The inner store should NOT have plaintext.
    raw = await inner.read("sid")
    assert raw is not None
    assert "_encrypted" in raw
    assert "user_id" not in str(raw)

    # The outer store decrypts correctly.
    data = await store.read("sid")
    assert data == {"user_id": 42, "role": "admin"}


async def test_encrypted_store_wrong_key_returns_none() -> None:
    enc1 = _enc()
    enc2 = _enc()
    inner = MemorySessionStore()
    store1 = EncryptedSessionStore(inner=inner, encrypter=enc1)
    store2 = EncryptedSessionStore(inner=inner, encrypter=enc2)

    await store1.write("sid", {"secret": True}, ttl_seconds=60)
    assert await store2.read("sid") is None  # wrong key → None


async def test_encrypted_store_destroy() -> None:
    enc = _enc()
    inner = MemorySessionStore()
    store = EncryptedSessionStore(inner=inner, encrypter=enc)

    await store.write("sid", {"x": 1}, ttl_seconds=60)
    await store.destroy("sid")
    assert await store.read("sid") is None


async def test_encrypted_store_stores_python_objects() -> None:
    from datetime import UTC, datetime

    enc = _enc()
    store = EncryptedSessionStore(inner=MemorySessionStore(), encrypter=enc)
    now = datetime.now(UTC)
    await store.write("sid", {"ts": now, "tags": frozenset({"a"})}, ttl_seconds=60)
    data = await store.read("sid")
    assert data is not None
    assert data["ts"] == now
    assert isinstance(data["tags"], frozenset)
