"""Tests for the S3 storage driver with a thin in-process mock.

We avoid moto because its async compatibility with aioboto3 is
fragile across version pairs. Instead we mock the aioboto3 session
so the driver's logic — key building, error mapping, URL generation,
signed URL forwarding — is exercised without network I/O.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest

pytest.importorskip("aioboto3")

from pylar.storage.drivers.s3 import S3Storage
from pylar.storage.exceptions import (
    FileNotFoundError as StorageFileNotFoundError,
)

# ----------------------------------------------------------- fake client


class _NotFoundError(Exception):
    """Simulates botocore ClientError with a 404 code."""

    def __init__(self) -> None:
        self.response = {"Error": {"Code": "404"}}
        super().__init__("Not found")


class _FakeBody:
    """Async readable wrapping bytes for get_object responses."""

    def __init__(self, data: bytes) -> None:
        self._data = data

    async def read(self) -> bytes:
        return self._data

    async def __aenter__(self) -> _FakeBody:
        return self

    async def __aexit__(self, *_: object) -> None:
        pass


class _FakeS3Client:
    """Minimal in-memory S3 client — enough for the driver's six methods."""

    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}

    class Exceptions:
        NoSuchKey = _NotFoundError

    exceptions = Exceptions

    async def head_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        if Key not in self._objects:
            raise _NotFoundError()
        return {"ContentLength": len(self._objects[Key])}

    async def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        if Key not in self._objects:
            raise _NotFoundError()
        return {"Body": _FakeBody(self._objects[Key])}

    async def put_object(
        self, *, Bucket: str, Key: str, Body: bytes
    ) -> None:
        self._objects[Key] = Body

    async def delete_object(self, *, Bucket: str, Key: str) -> None:
        self._objects.pop(Key, None)

    async def generate_presigned_url(
        self, method: str, Params: dict[str, str], ExpiresIn: int
    ) -> str:
        key = Params["Key"]
        return f"https://signed.example.com/{key}?expires={ExpiresIn}"

    async def __aenter__(self) -> _FakeS3Client:
        return self

    async def __aexit__(self, *_: object) -> None:
        pass


class _FakeSession:
    """Replaces aioboto3.Session for the test suite."""

    def __init__(self, fake_client: _FakeS3Client, region: str = "us-east-1") -> None:
        self._client = fake_client
        self.region_name = region

    @asynccontextmanager
    async def client(
        self,
        service: str,
        **kwargs: object,
    ) -> AsyncIterator[_FakeS3Client]:
        yield self._client


@pytest.fixture
def storage() -> S3Storage:
    fake_client = _FakeS3Client()
    store = S3Storage(
        bucket="test-bucket",
        prefix="uploads",
        region="us-east-1",
        base_url="https://cdn.example.com",
    )
    # Inject the fake session so no real AWS calls happen.
    store._session = _FakeSession(fake_client)  # type: ignore[assignment]
    return store


@pytest.fixture
def storage_no_base_url() -> S3Storage:
    fake_client = _FakeS3Client()
    store = S3Storage(
        bucket="test-bucket",
        prefix="media",
        region="eu-central-1",
    )
    store._session = _FakeSession(fake_client, region="eu-central-1")  # type: ignore[assignment]
    return store


# ----------------------------------------------------------- basic CRUD


async def test_put_and_get_round_trip(storage: S3Storage) -> None:
    await storage.put("hello.txt", b"hello world")
    data = await storage.get("hello.txt")
    assert data == b"hello world"


async def test_exists_true_after_put(storage: S3Storage) -> None:
    await storage.put("doc.pdf", b"%PDF")
    assert await storage.exists("doc.pdf") is True


async def test_exists_false_before_put(storage: S3Storage) -> None:
    assert await storage.exists("nope.txt") is False


async def test_delete_removes_object(storage: S3Storage) -> None:
    await storage.put("tmp.txt", b"gone soon")
    await storage.delete("tmp.txt")
    assert await storage.exists("tmp.txt") is False


async def test_delete_is_idempotent(storage: S3Storage) -> None:
    await storage.delete("never-existed.txt")  # no error


async def test_size_returns_content_length(storage: S3Storage) -> None:
    content = b"exactly 20 bytes!.."
    await storage.put("sized.bin", content)
    assert await storage.size("sized.bin") == len(content)


# ----------------------------------------------------------- error paths


async def test_get_missing_raises_file_not_found(storage: S3Storage) -> None:
    with pytest.raises(StorageFileNotFoundError):
        await storage.get("ghost.txt")


async def test_size_missing_raises_file_not_found(storage: S3Storage) -> None:
    with pytest.raises(StorageFileNotFoundError):
        await storage.size("ghost.txt")


# ----------------------------------------------------------------- URLs


async def test_url_uses_base_url_with_prefix(storage: S3Storage) -> None:
    url = await storage.url("photo.jpg")
    assert url == "https://cdn.example.com/uploads/photo.jpg"


async def test_url_without_base_url_builds_canonical(
    storage_no_base_url: S3Storage,
) -> None:
    url = await storage_no_base_url.url("file.txt")
    assert url == "https://test-bucket.s3.eu-central-1.amazonaws.com/media/file.txt"


# ----------------------------------------------------------- nested paths


async def test_nested_paths_round_trip(storage: S3Storage) -> None:
    await storage.put("a/b/c/deep.txt", b"nested")
    assert await storage.get("a/b/c/deep.txt") == b"nested"
    assert await storage.exists("a/b/c/deep.txt") is True


# ----------------------------------------------------------- signed URL


async def test_signed_url_returns_string(storage: S3Storage) -> None:
    await storage.put("secret.pdf", b"data")
    url = await storage.signed_url("secret.pdf", ttl=300)
    assert "signed.example.com" in url
    assert "300" in url


# --------------------------------------------------------- key building


def test_key_includes_prefix(storage: S3Storage) -> None:
    assert storage._key("photo.jpg") == "uploads/photo.jpg"


def test_key_strips_leading_slash(storage: S3Storage) -> None:
    assert storage._key("/photo.jpg") == "uploads/photo.jpg"


def test_key_without_prefix() -> None:
    store = S3Storage(bucket="b", prefix="")
    assert store._key("file.txt") == "file.txt"


# -------------------------------------------------------- binary content


async def test_binary_content_round_trip(storage: S3Storage) -> None:
    binary = bytes(range(256)) * 100
    await storage.put("binary.bin", binary)
    assert await storage.get("binary.bin") == binary


# ----------------------------------------------------- protocol compliance


def test_satisfies_filesystem_store_protocol() -> None:
    from pylar.storage import FilesystemStore

    store = S3Storage(bucket="b")
    assert isinstance(store, FilesystemStore)
