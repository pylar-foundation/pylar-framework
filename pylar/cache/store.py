"""The :class:`CacheStore` Protocol that every cache driver implements."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class CacheStore(Protocol):
    """A minimal key-value store with optional time-to-live.

    Pylar deliberately keeps the contract small (four methods) so that
    swapping in-memory for Redis, the database, or any other backing store
    is a one-line container rebinding. Higher-level conveniences such as
    ``has`` and ``remember`` live on :class:`Cache`, which wraps a store.

    All operations are async — even ``MemoryCacheStore`` exposes async
    methods so the call sites stay uniform regardless of which driver is
    bound. The ``Any`` return type from :meth:`get` reflects that the
    store is type-erased; callers know what they put in and how to
    interpret what they pop out.
    """

    async def get(self, key: str) -> Any: ...

    async def put(self, key: str, value: Any, *, ttl: int | None = None) -> None: ...

    async def forget(self, key: str) -> None: ...

    async def flush(self) -> None: ...
