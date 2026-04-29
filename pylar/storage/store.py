"""The :class:`FilesystemStore` Protocol that every storage driver implements."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class FilesystemStore(Protocol):
    """A minimal POSIX-flavoured filesystem abstraction.

    Pylar's storage layer is intentionally narrow — six methods covering
    presence, read, write, delete, size, and public URL. Drivers extend
    the surface for their own affordances (signed URLs, multipart upload,
    server-side copy) without changing the contract every consumer
    depends on.

    All paths are POSIX-style strings rooted at the store's configured
    base. Drivers are responsible for sandboxing those paths inside the
    base — see :class:`LocalStorage` for the reference implementation.
    """

    async def exists(self, path: str) -> bool: ...

    async def get(self, path: str) -> bytes: ...

    async def put(self, path: str, contents: bytes) -> None: ...

    async def delete(self, path: str) -> None: ...

    async def size(self, path: str) -> int: ...

    async def url(self, path: str) -> str: ...
