"""Exceptions for the encryption layer."""

from __future__ import annotations


class EncryptionError(Exception):
    """Base class for encryption errors — bad key, bad config."""


class DecryptionError(EncryptionError):
    """Raised when decryption fails — tampered data or wrong key."""
