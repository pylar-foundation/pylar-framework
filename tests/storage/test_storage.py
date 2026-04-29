"""Behavioural tests for the storage drivers."""

from __future__ import annotations

from pathlib import Path

import pytest

from pylar.storage import (
    FileNotFoundError,
    FilesystemStore,
    LocalStorage,
    MemoryStorage,
    PathTraversalError,
)

# ------------------------------------------------------------- LocalStorage


@pytest.fixture
def local(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path / "uploads", base_url="https://cdn.example.com/files")


async def test_put_creates_parent_directories(local: LocalStorage) -> None:
    await local.put("nested/deep/file.txt", b"hello")
    assert (local.root / "nested" / "deep" / "file.txt").read_bytes() == b"hello"


async def test_get_returns_bytes(local: LocalStorage) -> None:
    await local.put("a.txt", b"abc")
    assert await local.get("a.txt") == b"abc"


async def test_get_missing_raises_storage_error(local: LocalStorage) -> None:
    with pytest.raises(FileNotFoundError, match=r"missing\.txt"):
        await local.get("missing.txt")


async def test_exists(local: LocalStorage) -> None:
    assert await local.exists("x.txt") is False
    await local.put("x.txt", b"x")
    assert await local.exists("x.txt") is True


async def test_size(local: LocalStorage) -> None:
    await local.put("k.bin", b"1234567890")
    assert await local.size("k.bin") == 10


async def test_delete_is_idempotent(local: LocalStorage) -> None:
    await local.delete("does-not-exist.txt")  # no error
    await local.put("k.txt", b"v")
    await local.delete("k.txt")
    assert await local.exists("k.txt") is False


async def test_url_uses_base_url(local: LocalStorage) -> None:
    assert await local.url("posts/1.jpg") == "https://cdn.example.com/files/posts/1.jpg"


async def test_url_without_base_url_returns_relative(tmp_path: Path) -> None:
    store = LocalStorage(tmp_path)
    assert await store.url("/a/b.txt") == "a/b.txt"


async def test_path_traversal_blocked_on_put(local: LocalStorage) -> None:
    with pytest.raises(PathTraversalError):
        await local.put("../escaped.txt", b"x")


async def test_path_traversal_blocked_on_url(local: LocalStorage) -> None:
    with pytest.raises(PathTraversalError):
        await local.url("../../etc/passwd")


async def test_protocol_is_runtime_checkable(local: LocalStorage) -> None:
    assert isinstance(local, FilesystemStore)


# ------------------------------------------------------------- MemoryStorage


@pytest.fixture
def memory() -> MemoryStorage:
    return MemoryStorage()


async def test_memory_put_and_get(memory: MemoryStorage) -> None:
    await memory.put("k", b"v")
    assert await memory.get("k") == b"v"


async def test_memory_get_missing_raises(memory: MemoryStorage) -> None:
    with pytest.raises(FileNotFoundError):
        await memory.get("nope")


async def test_memory_size(memory: MemoryStorage) -> None:
    await memory.put("a", b"hello")
    assert await memory.size("a") == 5


async def test_memory_url_uses_scheme(memory: MemoryStorage) -> None:
    assert await memory.url("a/b.txt") == "memory://a/b.txt"


async def test_memory_satisfies_protocol(memory: MemoryStorage) -> None:
    assert isinstance(memory, FilesystemStore)
