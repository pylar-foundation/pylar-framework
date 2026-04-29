"""Amazon S3 storage driver.

Implements the :class:`pylar.storage.FilesystemStore` Protocol against
an S3 bucket, so application code that depends on ``FilesystemStore``
works identically whether the bound driver is local disk, in-memory,
or a cloud bucket. Install through the ``pylar[storage-s3]`` extra
which pulls in ``aioboto3``.

The driver delegates every call to ``aioboto3``'s async context-managed
client so the event loop never blocks on network I/O. Connection
pooling, retries, and credential resolution are handled by botocore
underneath — pylar does not re-implement any of that.

Usage::

    from pylar.storage.drivers.s3 import S3Storage

    storage = S3Storage(
        bucket="my-app-uploads",
        prefix="media/",                     # optional key prefix
        region="eu-central-1",
        endpoint_url="https://s3.eu-central-1.amazonaws.com",
        base_url="https://cdn.example.com",  # for url()
    )

Credentials are resolved through the standard boto chain
(env vars → ``~/.aws/credentials`` → instance profile → ECS task role).
Pass ``aws_access_key_id`` and ``aws_secret_access_key`` explicitly
for non-standard setups; they forward straight to the underlying
``aioboto3.Session``.
"""

from __future__ import annotations

from typing import Any

try:
    import aioboto3
except ImportError:  # pragma: no cover
    raise ImportError(
        "S3Storage requires the 'aioboto3' package. "
        "Install it with: pip install 'pylar[storage-s3]'"
    ) from None

from pylar.storage.exceptions import FileNotFoundError as StorageFileNotFoundError


class S3Storage:
    """A :class:`FilesystemStore` backed by an Amazon S3 bucket.

    All six protocol methods map onto a single S3 API call each,
    keeping the driver thin and predictable:

    * ``exists`` → ``head_object``
    * ``get``    → ``get_object`` → read ``Body``
    * ``put``    → ``put_object``
    * ``delete`` → ``delete_object``
    * ``size``   → ``head_object`` → ``ContentLength``
    * ``url``    → ``base_url + prefix + path`` (public URL, no signing)

    For pre-signed download URLs use :meth:`signed_url` — it is an
    S3-specific extension outside the Protocol surface.
    """

    def __init__(
        self,
        *,
        bucket: str,
        prefix: str = "",
        region: str = "",
        endpoint_url: str | None = None,
        base_url: str = "",
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
        signed_url_ttl: int = 3600,
    ) -> None:
        self._bucket = bucket
        self._prefix = prefix.strip("/")
        self._base_url = base_url.rstrip("/") if base_url else ""
        self._signed_url_ttl = signed_url_ttl

        session_kwargs: dict[str, Any] = {}
        if region:
            session_kwargs["region_name"] = region
        if aws_access_key_id:
            session_kwargs["aws_access_key_id"] = aws_access_key_id
        if aws_secret_access_key:
            session_kwargs["aws_secret_access_key"] = aws_secret_access_key
        self._session = aioboto3.Session(**session_kwargs)
        self._endpoint_url = endpoint_url

    # ----------------------------------------------------------------- Protocol

    async def exists(self, path: str) -> bool:
        key = self._key(path)
        async with self._client() as s3:
            try:
                await s3.head_object(Bucket=self._bucket, Key=key)
                return True
            except s3.exceptions.NoSuchKey:
                return False
            except Exception as exc:
                # botocore raises ClientError with 404 code, not
                # NoSuchKey, depending on the backend.
                if _is_not_found(exc):
                    return False
                raise

    async def get(self, path: str) -> bytes:
        key = self._key(path)
        async with self._client() as s3:
            try:
                response = await s3.get_object(Bucket=self._bucket, Key=key)
                async with response["Body"] as stream:
                    return await stream.read()  # type: ignore[no-any-return]
            except Exception as exc:
                if _is_not_found(exc):
                    raise StorageFileNotFoundError(path) from exc
                raise

    async def put(self, path: str, contents: bytes) -> None:
        key = self._key(path)
        async with self._client() as s3:
            await s3.put_object(
                Bucket=self._bucket, Key=key, Body=contents
            )

    async def delete(self, path: str) -> None:
        key = self._key(path)
        async with self._client() as s3:
            # S3 delete is idempotent — deleting a non-existent key
            # is a successful no-op.
            await s3.delete_object(Bucket=self._bucket, Key=key)

    async def size(self, path: str) -> int:
        key = self._key(path)
        async with self._client() as s3:
            try:
                response = await s3.head_object(Bucket=self._bucket, Key=key)
                return int(response["ContentLength"])
            except Exception as exc:
                if _is_not_found(exc):
                    raise StorageFileNotFoundError(path) from exc
                raise

    async def url(self, path: str) -> str:
        key = self._key(path)
        if self._base_url:
            return f"{self._base_url}/{key}"
        # Fallback: construct the canonical S3 URL.
        if self._endpoint_url:
            return f"{self._endpoint_url.rstrip('/')}/{self._bucket}/{key}"
        region = self._session.region_name or "us-east-1"
        return f"https://{self._bucket}.s3.{region}.amazonaws.com/{key}"

    # ------------------------------------------------------------- S3-specific

    async def signed_url(
        self, path: str, *, ttl: int | None = None
    ) -> str:
        """Generate a pre-signed download URL valid for *ttl* seconds.

        This is an S3-specific extension — the ``FilesystemStore``
        Protocol does not include it, so only code that knows it is
        talking to S3 should call this method. For everything else,
        :meth:`url` returns a plain public URL.
        """
        key = self._key(path)
        expires_in = ttl if ttl is not None else self._signed_url_ttl
        async with self._client() as s3:
            return await s3.generate_presigned_url(  # type: ignore[no-any-return]
                "get_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=expires_in,
            )

    # ---------------------------------------------------------------- internals

    def _key(self, path: str) -> str:
        """Resolve *path* into a full S3 object key under the configured prefix."""
        clean = path.lstrip("/")
        if self._prefix:
            return f"{self._prefix}/{clean}"
        return clean

    def _client(self) -> Any:
        """Return an async context-managed S3 client."""
        kwargs: dict[str, Any] = {}
        if self._endpoint_url:
            kwargs["endpoint_url"] = self._endpoint_url
        return self._session.client("s3", **kwargs)


def _is_not_found(exc: BaseException) -> bool:
    """Check whether *exc* is a botocore 404-style error."""
    # botocore wraps HTTP 404 into a ClientError with an error code.
    error_code = getattr(
        getattr(exc, "response", None), "get", lambda *_: None
    )
    if callable(error_code):
        resp = getattr(exc, "response", None)
        if isinstance(resp, dict):
            code = resp.get("Error", {}).get("Code", "")
            return code in ("404", "NoSuchKey")
    return "404" in str(exc) or "NoSuchKey" in str(exc)
