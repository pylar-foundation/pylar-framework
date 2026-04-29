"""Tests for the GCS storage driver with an in-process client mock.

We don't want tests to depend on GCS credentials or the network, so
the tests inject a fake async client that implements the subset of
``gcloud.aio.storage.Storage`` the driver actually uses. This keeps
the driver's logic (key building, error mapping, URL generation)
covered without any external dependency.
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("gcloud.aio.storage")

from pylar.storage.drivers.gcs import GCSStorage
from pylar.storage.exceptions import (
    FileNotFoundError as StorageFileNotFoundError,
)


class _NotFoundError(Exception):
    """Simulates a gcloud-aio-storage 404 response."""

    status = 404

    def __init__(self) -> None:
        super().__init__("404 Not Found")


class _FakeGcsClient:
    """Minimal stand-in for gcloud.aio.storage.Storage."""

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], bytes] = {}
        self.deleted_keys: list[tuple[str, str]] = []

    async def upload(
        self, bucket: str, key: str, data: bytes,
    ) -> None:
        self._store[(bucket, key)] = data

    async def download(self, bucket: str, key: str) -> bytes:
        if (bucket, key) not in self._store:
            raise _NotFoundError()
        return self._store[(bucket, key)]

    async def download_metadata(
        self, bucket: str, key: str,
    ) -> dict[str, Any]:
        if (bucket, key) not in self._store:
            raise _NotFoundError()
        return {"size": str(len(self._store[(bucket, key)]))}

    async def delete(self, bucket: str, key: str) -> None:
        if (bucket, key) not in self._store:
            raise _NotFoundError()
        del self._store[(bucket, key)]
        self.deleted_keys.append((bucket, key))

    async def close(self) -> None:
        pass


@pytest.fixture
def storage(monkeypatch: pytest.MonkeyPatch) -> GCSStorage:
    """A GCSStorage that talks to a fake in-memory client."""
    fake = _FakeGcsClient()
    store = GCSStorage(bucket="test-bucket", prefix="media")
    # Replace the private client with our fake. The driver only calls
    # the four methods we stubbed.
    store._client = fake  # type: ignore[assignment]
    return store


# ----------------------------------------------------------- Protocol


async def test_put_then_get_round_trip(storage: GCSStorage) -> None:
    await storage.put("hello.txt", b"hello world")
    assert await storage.get("hello.txt") == b"hello world"


async def test_exists_after_put(storage: GCSStorage) -> None:
    assert await storage.exists("missing.txt") is False
    await storage.put("a.txt", b"x")
    assert await storage.exists("a.txt") is True


async def test_get_missing_raises_storage_error(storage: GCSStorage) -> None:
    with pytest.raises(StorageFileNotFoundError):
        await storage.get("nope.txt")


async def test_size_missing_raises_storage_error(storage: GCSStorage) -> None:
    with pytest.raises(StorageFileNotFoundError):
        await storage.size("nope.txt")


async def test_size_returns_content_length(storage: GCSStorage) -> None:
    await storage.put("f.bin", b"abcd")
    assert await storage.size("f.bin") == 4


async def test_delete_idempotent(storage: GCSStorage) -> None:
    """Deleting a non-existent object must not raise."""
    await storage.delete("nope.txt")  # silently swallowed


async def test_delete_removes_object(storage: GCSStorage) -> None:
    await storage.put("a.txt", b"1")
    await storage.delete("a.txt")
    assert await storage.exists("a.txt") is False


async def test_url_uses_configured_base_url() -> None:
    s = GCSStorage(
        bucket="b", prefix="media", base_url="https://cdn.example.com",
    )
    assert await s.url("file.jpg") == "https://cdn.example.com/media/file.jpg"


async def test_url_falls_back_to_googleapis_canonical_url() -> None:
    s = GCSStorage(bucket="my-bucket", prefix="media")
    assert await s.url("file.jpg") == (
        "https://storage.googleapis.com/my-bucket/media/file.jpg"
    )


async def test_prefix_empty_uses_plain_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without a prefix the key equals the caller's path."""
    fake = _FakeGcsClient()
    s = GCSStorage(bucket="b", prefix="")
    s._client = fake  # type: ignore[assignment]
    await s.put("hello.txt", b"x")
    assert ("b", "hello.txt") in fake._store


async def test_leading_slash_stripped(monkeypatch: pytest.MonkeyPatch) -> None:
    """Paths starting with ``/`` must not double up under the prefix."""
    fake = _FakeGcsClient()
    s = GCSStorage(bucket="b", prefix="media")
    s._client = fake  # type: ignore[assignment]
    await s.put("/hello.txt", b"x")
    assert ("b", "media/hello.txt") in fake._store
