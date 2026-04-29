"""In-process storage driver — used by tests and ephemeral fixtures."""

from __future__ import annotations

from pylar.storage.exceptions import FileNotFoundError as StorageFileNotFoundError


class MemoryStorage:
    """A dict-backed :class:`FilesystemStore` with no on-disk presence."""

    def __init__(self) -> None:
        self._files: dict[str, bytes] = {}

    async def exists(self, path: str) -> bool:
        return path in self._files

    async def get(self, path: str) -> bytes:
        try:
            return self._files[path]
        except KeyError as exc:
            raise StorageFileNotFoundError(path) from exc

    async def put(self, path: str, contents: bytes) -> None:
        self._files[path] = contents

    async def delete(self, path: str) -> None:
        self._files.pop(path, None)

    async def size(self, path: str) -> int:
        try:
            return len(self._files[path])
        except KeyError as exc:
            raise StorageFileNotFoundError(path) from exc

    async def url(self, path: str) -> str:
        return f"memory://{path}"

    async def list_files(
        self, prefix: str = "", *, recursive: bool = False
    ) -> list[str]:
        if not prefix:
            return list(self._files.keys())
        return [k for k in self._files if k.startswith(prefix)]

    async def metadata(self, path: str) -> dict[str, object]:
        if path not in self._files:
            raise StorageFileNotFoundError(path)
        return {
            "size": len(self._files[path]),
            "last_modified": None,
            "content_type": "application/octet-stream",
        }
