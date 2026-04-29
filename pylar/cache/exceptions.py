"""Exceptions raised by the cache layer."""

from __future__ import annotations


class CacheError(Exception):
    """Base class for cache errors."""


class CacheLockError(CacheError):
    """Raised when a :class:`CacheLock` cannot be acquired in time."""
