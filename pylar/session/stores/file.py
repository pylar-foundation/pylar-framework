"""On-disk session store — one pickle file per session id.

The payload is serialised with :mod:`pickle` (protocol 5) so the
session can carry arbitrary Python objects — ``datetime`` instances,
frozen dataclasses, ORM snapshots, anything the application puts
there. Security-wise this is safe because session data is
*server-controlled*: only the application writes the files, and the
session id in the cookie is HMAC-signed so an attacker cannot point
it at a crafted file without the secret key.
"""

from __future__ import annotations

import asyncio
import hashlib
import pickle
import time
from pathlib import Path
from typing import Any

from pylar.support.serializer import dump, safe_load


class FileSessionStore:
    """Persists session payloads as pickle files inside a sandbox directory.

    Like :class:`pylar.cache.FileCacheStore` the file name is the
    SHA-256 of the session id, so even pathological cookie tampering
    cannot escape the root. The body is a pickled ``(data, expires_at)``
    tuple; expired entries are evicted lazily on read.
    """

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    async def read(self, session_id: str) -> dict[str, Any] | None:
        path = self._path_for(session_id)
        return await asyncio.to_thread(self._read_sync, path)

    async def write(
        self,
        session_id: str,
        data: dict[str, Any],
        *,
        ttl_seconds: int,
    ) -> None:
        path = self._path_for(session_id)
        expires_at = time.time() + ttl_seconds
        await asyncio.to_thread(self._write_sync, path, data, expires_at)

    async def destroy(self, session_id: str) -> None:
        path = self._path_for(session_id)
        await asyncio.to_thread(self._unlink_sync, path)

    # ------------------------------------------------------------------ internals

    def _path_for(self, session_id: str) -> Path:
        digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
        return self._root / f"{digest}.session"

    def _read_sync(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            with path.open("rb") as fh:
                data, expires_at = safe_load(fh)
        except (OSError, pickle.UnpicklingError, EOFError, ValueError):
            return None
        if not isinstance(expires_at, (int, float)) or time.time() >= expires_at:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            return None
        return data if isinstance(data, dict) else None

    def _write_sync(
        self,
        path: Path,
        data: dict[str, Any],
        expires_at: float,
    ) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".session.tmp")
        with tmp.open("wb") as fh:
            dump((data, expires_at), fh)
        tmp.replace(path)

    def _unlink_sync(self, path: Path) -> None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
