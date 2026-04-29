"""On-disk cache driver — pickle blobs under a sandbox directory.

Useful for single-host applications that want cache survival across
process restarts without operating a separate service like Redis. Each
key maps to one file whose name is the SHA-256 of the key (so arbitrary
characters in user-supplied keys never escape the sandbox), and the
file body is a pickled ``(value, expires_at)`` tuple. The same lazy
eviction strategy that :class:`MemoryCacheStore` uses applies here:
expired entries are removed on read rather than swept by a background
task.

The driver wraps every filesystem call in :func:`asyncio.to_thread` so
the surface stays async even though the underlying syscalls are
blocking — pylar's ``LocalStorage`` follows the same pattern, and the
two modules treat each other as siblings rather than dependencies.
"""

from __future__ import annotations

import asyncio
import hashlib
import pickle
import time
from pathlib import Path
from typing import Any

from pylar.support.serializer import dump, safe_load


class FileCacheStore:
    """Cache driver that persists entries as pickle blobs on disk.

    The *root* directory is created on first write if it does not
    already exist. All cache files live directly under that directory;
    pylar does not shard into subdirectories because the typical key
    cardinality is small enough that a single ``ls`` is fine. If your
    workload demonstrably needs sharding, switch to a real persistent
    driver — by then you almost certainly want Redis anyway.
    """

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    async def get(self, key: str) -> Any:
        path = self._path_for(key)
        return await asyncio.to_thread(self._read_sync, path)

    async def put(self, key: str, value: Any, *, ttl: int | None = None) -> None:
        path = self._path_for(key)
        expires_at = time.time() + ttl if ttl is not None else None
        await asyncio.to_thread(self._write_sync, path, value, expires_at)

    async def forget(self, key: str) -> None:
        path = self._path_for(key)
        await asyncio.to_thread(self._unlink_sync, path)

    async def flush(self) -> None:
        await asyncio.to_thread(self._flush_sync)

    # ------------------------------------------------------------------ internals

    def _path_for(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self._root / f"{digest}.cache"

    def _read_sync(self, path: Path) -> Any:
        if not path.exists():
            return None
        try:
            with path.open("rb") as fh:
                value, expires_at = safe_load(fh)
        except (OSError, pickle.UnpicklingError, EOFError):
            return None
        if expires_at is not None and time.time() >= expires_at:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            return None
        return value

    def _write_sync(self, path: Path, value: Any, expires_at: float | None) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        # Atomic-ish write: dump to a temp file in the same directory and
        # replace the target so a half-written file never wins a read.
        tmp = path.with_suffix(".cache.tmp")
        with tmp.open("wb") as fh:
            dump((value, expires_at), fh)
        tmp.replace(path)

    def _unlink_sync(self, path: Path) -> None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    def _flush_sync(self) -> None:
        if not self._root.exists():
            return
        for entry in self._root.glob("*.cache"):
            try:
                entry.unlink()
            except FileNotFoundError:
                pass
