"""Google Cloud Storage driver.

Implements the :class:`pylar.storage.FilesystemStore` Protocol against
a GCS bucket. Install through the ``pylar[storage-gcs]`` extra which
pulls in ``gcloud-aio-storage`` — a fully async GCS client maintained
by the Talkiq team.

Credentials follow Google's standard resolution order:
``GOOGLE_APPLICATION_CREDENTIALS`` env var, GCE metadata service,
Cloud Run / GKE workload identity, or an explicit *service_file*
path passed to the constructor. Pylar never re-implements auth —
the client library handles it.

Usage::

    from pylar.storage.drivers.gcs import GCSStorage

    storage = GCSStorage(
        bucket="my-app-uploads",
        prefix="media/",                          # optional key prefix
        base_url="https://storage.googleapis.com/my-app-uploads",
        service_file="/etc/pylar/gcs-sa.json",    # optional
    )

The driver mirrors the S3 driver's shape on purpose: the
``FilesystemStore`` Protocol is the only thing callers should depend
on, and signed URLs are exposed as an optional ``signed_url``
extension outside that Protocol.
"""

from __future__ import annotations

from typing import Any

try:
    from gcloud.aio.storage import Storage
except ImportError:  # pragma: no cover
    raise ImportError(
        "GCSStorage requires the 'gcloud-aio-storage' package. "
        "Install it with: pip install 'pylar[storage-gcs]'"
    ) from None

from pylar.storage.exceptions import FileNotFoundError as StorageFileNotFoundError


class GCSStorage:
    """A :class:`FilesystemStore` backed by a Google Cloud Storage bucket.

    Each Protocol method maps onto a single GCS API call:

    * ``exists`` → ``download_metadata`` (404 → False)
    * ``get``    → ``download`` → bytes
    * ``put``    → ``upload``
    * ``delete`` → ``delete`` (silently swallows 404 for idempotency)
    * ``size``   → ``download_metadata`` → ``size`` field
    * ``url``    → ``base_url + prefix + path`` (public URL)

    A single long-lived :class:`gcloud.aio.storage.Storage` instance is
    reused across requests; it manages its own aiohttp session and
    connection pool.
    """

    def __init__(
        self,
        *,
        bucket: str,
        prefix: str = "",
        base_url: str = "",
        service_file: str | None = None,
        signed_url_ttl: int = 3600,
    ) -> None:
        self._bucket = bucket
        self._prefix = prefix.strip("/")
        self._base_url = base_url.rstrip("/") if base_url else ""
        self._signed_url_ttl = signed_url_ttl
        self._service_file = service_file
        # Client is built lazily: gcloud-aio-storage constructs an
        # aiohttp session eagerly, which crashes outside a running
        # event loop. We defer until the first async call.
        self._client_instance: Any = None

    @property
    def _client(self) -> Any:
        if self._client_instance is None:
            self._client_instance = Storage(service_file=self._service_file)
        return self._client_instance

    @_client.setter
    def _client(self, value: Any) -> None:
        self._client_instance = value

    # ----------------------------------------------------------------- Protocol

    async def exists(self, path: str) -> bool:
        key = self._key(path)
        try:
            await self._client.download_metadata(self._bucket, key)
            return True
        except Exception as exc:
            if _is_not_found(exc):
                return False
            raise

    async def get(self, path: str) -> bytes:
        key = self._key(path)
        try:
            data = await self._client.download(self._bucket, key)
            return bytes(data)
        except Exception as exc:
            if _is_not_found(exc):
                raise StorageFileNotFoundError(path) from exc
            raise

    async def put(self, path: str, contents: bytes) -> None:
        key = self._key(path)
        await self._client.upload(self._bucket, key, contents)

    async def delete(self, path: str) -> None:
        key = self._key(path)
        try:
            await self._client.delete(self._bucket, key)
        except Exception as exc:
            if _is_not_found(exc):
                return  # idempotent — match S3 semantics
            raise

    async def size(self, path: str) -> int:
        key = self._key(path)
        try:
            meta = await self._client.download_metadata(self._bucket, key)
            # GCS returns metadata as a dict; "size" is a string of bytes.
            raw_size = meta.get("size", "0") if isinstance(meta, dict) else 0
            return int(raw_size)
        except Exception as exc:
            if _is_not_found(exc):
                raise StorageFileNotFoundError(path) from exc
            raise

    async def url(self, path: str) -> str:
        key = self._key(path)
        if self._base_url:
            return f"{self._base_url}/{key}"
        return f"https://storage.googleapis.com/{self._bucket}/{key}"

    # ------------------------------------------------------------- GCS-specific

    async def signed_url(
        self, path: str, *, ttl: int | None = None
    ) -> str:
        """Generate a V4 pre-signed download URL for *path*.

        Requires service-account credentials. Anonymous/default
        credential chains that lack a private key raise here — fall
        back to :meth:`url` when public URLs are enough.
        """
        key = self._key(path)
        expires_in = ttl if ttl is not None else self._signed_url_ttl
        bucket = self._client.get_bucket(self._bucket)
        blob = await bucket.get_blob(key)
        return await blob.get_signed_url(expiration=expires_in)  # type: ignore[no-any-return]

    async def close(self) -> None:
        """Close the underlying aiohttp session."""
        await self._client.close()

    # ---------------------------------------------------------------- internals

    def _key(self, path: str) -> str:
        """Resolve *path* into a full GCS object name under the configured prefix."""
        clean = path.lstrip("/")
        if self._prefix:
            return f"{self._prefix}/{clean}"
        return clean


def _is_not_found(exc: BaseException) -> bool:
    """Check whether *exc* represents a GCS 404."""
    message = str(exc)
    status = getattr(exc, "status", None)
    return status == 404 or "404" in message or "Not Found" in message
