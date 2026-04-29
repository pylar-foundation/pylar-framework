"""In-process session store — useful for tests, dev, and single-instance servers."""

from __future__ import annotations

import time
from typing import Any


class MemorySessionStore:
    """Dict-backed session store with monotonic TTL."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[dict[str, Any], float]] = {}

    async def read(self, session_id: str) -> dict[str, Any] | None:
        entry = self._data.get(session_id)
        if entry is None:
            return None
        data, expires_at = entry
        if time.time() >= expires_at:
            del self._data[session_id]
            return None
        return dict(data)

    async def write(
        self,
        session_id: str,
        data: dict[str, Any],
        *,
        ttl_seconds: int,
    ) -> None:
        self._data[session_id] = (dict(data), time.time() + ttl_seconds)

    async def destroy(self, session_id: str) -> None:
        self._data.pop(session_id, None)
