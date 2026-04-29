"""In-process cache driver — useful for tests, dev, and single-process apps."""

from __future__ import annotations

import time
from typing import Any


class MemoryCacheStore:
    """A dict-backed cache with monotonic TTL.

    Expired entries are evicted lazily on read *and* periodically
    during writes (every :attr:`_GC_INTERVAL` puts) so abandoned
    keys do not accumulate indefinitely.
    """

    _GC_INTERVAL = 100  # run GC every N writes

    def __init__(self) -> None:
        self._data: dict[str, tuple[Any, float | None]] = {}
        self._gc_counter = 0

    async def get(self, key: str) -> Any:
        entry = self._data.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if expires_at is not None and time.monotonic() >= expires_at:
            del self._data[key]
            return None
        return value

    async def put(self, key: str, value: Any, *, ttl: int | None = None) -> None:
        expires_at = time.monotonic() + ttl if ttl is not None else None
        self._data[key] = (value, expires_at)
        self._maybe_gc()

    async def forget(self, key: str) -> None:
        self._data.pop(key, None)

    async def flush(self) -> None:
        self._data.clear()
        self._gc_counter = 0

    def size(self) -> int:
        """Number of entries currently stored. Test affordance."""
        return len(self._data)

    # ----------------------------------------------------------- eviction

    def _maybe_gc(self) -> None:
        """Evict expired entries periodically to bound memory growth."""
        self._gc_counter += 1
        if self._gc_counter < self._GC_INTERVAL:
            return
        self._gc_counter = 0
        now = time.monotonic()
        expired = [
            k for k, (_, exp) in self._data.items()
            if exp is not None and now >= exp
        ]
        for k in expired:
            del self._data[k]
