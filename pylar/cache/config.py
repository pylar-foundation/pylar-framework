"""Typed configuration for the cache layer."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from pylar.config.schema import BaseConfig


class CacheConfig(BaseConfig):
    """Configuration for named cache stores.

    Define in ``config/cache.py``::

        from pylar.cache import CacheConfig

        config = CacheConfig(
            default="redis",
            stores={
                "redis": {"driver": "redis", "url": "redis://localhost:6379/0"},
                "array": {"driver": "memory"},
                "file":  {"driver": "file", "path": "storage/cache"},
            },
        )

    The ``default`` key names the store that :class:`CacheManager`
    returns when called without arguments. Each entry in ``stores``
    is a dict with at least a ``driver`` key.
    """

    default: str = "memory"
    stores: dict[str, dict[str, Any]] = Field(
        default_factory=lambda: {"memory": {"driver": "memory"}}
    )
