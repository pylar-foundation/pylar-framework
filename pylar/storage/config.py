"""Typed configuration for the storage layer."""

from __future__ import annotations

from pylar.config.schema import BaseConfig


class StorageConfig(BaseConfig):
    """Connection configuration consumed by :class:`LocalStorage`.

    ``root`` is the absolute path under which every file lives — every
    other ``path`` argument supplied to the store is interpreted as
    relative to this directory and is sandboxed to it.

    ``base_url`` is the public URL prefix used by :meth:`url` to render
    a browser-reachable address for stored files. It is empty by
    default; in that case ``url()`` returns a relative path.
    """

    root: str
    base_url: str = ""
