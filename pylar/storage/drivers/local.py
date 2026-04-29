"""Local filesystem driver — backed by ``pathlib`` and ``asyncio.to_thread``."""

from __future__ import annotations

import asyncio
from datetime import UTC
from pathlib import Path

from pylar.storage.exceptions import (
    FileNotFoundError as StorageFileNotFoundError,
)
from pylar.storage.exceptions import (
    PathTraversalError,
)


class LocalStorage:
    """A :class:`FilesystemStore` rooted at a directory on the local disk.

    Synchronous filesystem calls are dispatched through
    :func:`asyncio.to_thread` so that storage operations never block the
    event loop. The driver sandboxes every supplied path: an absolute
    target or one containing ``..`` segments that escapes the configured
    root raises :class:`PathTraversalError` before any I/O happens.
    """

    def __init__(self, root: Path, *, base_url: str = "") -> None:
        self._root = root.resolve()
        self._base_url = base_url
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    # ----------------------------------------------------------------- contract

    async def exists(self, path: str) -> bool:
        target = self._resolve(path)
        return await asyncio.to_thread(target.is_file)

    async def get(self, path: str) -> bytes:
        target = self._resolve(path)
        try:
            return await asyncio.to_thread(target.read_bytes)
        except FileNotFoundError as exc:
            raise StorageFileNotFoundError(path) from exc

    async def put(self, path: str, contents: bytes) -> None:
        target = self._resolve(path)
        await asyncio.to_thread(self._make_parent_and_write, target, contents)

    async def delete(self, path: str) -> None:
        target = self._resolve(path)
        await asyncio.to_thread(self._unlink_if_exists, target)

    async def size(self, path: str) -> int:
        target = self._resolve(path)
        try:
            return await asyncio.to_thread(lambda: target.stat().st_size)
        except FileNotFoundError as exc:
            raise StorageFileNotFoundError(path) from exc

    async def url(self, path: str) -> str:
        # Validate the path before producing a URL so callers cannot leak
        # outside-of-root references through this method either.
        self._resolve(path)
        if not self._base_url:
            return path.lstrip("/")
        return f"{self._base_url.rstrip('/')}/{path.lstrip('/')}"

    async def list_files(
        self, prefix: str = "", *, recursive: bool = False
    ) -> list[str]:
        """List files under *prefix*, relative to the storage root."""
        target = self._resolve(prefix) if prefix else self._root

        def _list() -> list[str]:
            if not target.is_dir():
                return []
            pattern = "**/*" if recursive else "*"
            return [
                str(p.relative_to(self._root))
                for p in target.glob(pattern)
                if p.is_file()
            ]

        return await asyncio.to_thread(_list)

    async def metadata(self, path: str) -> dict[str, object]:
        """Return file metadata: size, last_modified, content_type."""
        import mimetypes
        from datetime import datetime

        target = self._resolve(path)
        try:
            stat = await asyncio.to_thread(target.stat)
        except FileNotFoundError as exc:
            raise StorageFileNotFoundError(path) from exc
        content_type, _ = mimetypes.guess_type(str(target))
        return {
            "size": stat.st_size,
            "last_modified": datetime.fromtimestamp(stat.st_mtime, tz=UTC),
            "content_type": content_type or "application/octet-stream",
        }

    # ------------------------------------------------------------------ helpers

    def _resolve(self, path: str) -> Path:
        candidate = (self._root / path.lstrip("/")).resolve()
        try:
            candidate.relative_to(self._root)
        except ValueError as exc:
            raise PathTraversalError(path) from exc
        return candidate

    @staticmethod
    def _make_parent_and_write(target: Path, contents: bytes) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(contents)

    @staticmethod
    def _unlink_if_exists(target: Path) -> None:
        try:
            target.unlink()
        except FileNotFoundError:
            pass
