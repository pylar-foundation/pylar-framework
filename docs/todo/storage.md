# storage/ — backlog

## Cloud drivers

`S3Storage` landed behind ``pylar[storage-s3]`` (aioboto3). Two cloud
drivers remain on the wishlist:

* `GcsStorage` — Google Cloud Storage equivalent.
* `AzureBlobStorage` — Azure Blob Storage.

Both will follow the same shape as S3Storage — one API call per
Protocol method, optional dependency behind an extra.

## Streaming reads and writes

`get` and `put` materialise the entire file in memory. Add streaming
counterparts that return / accept an async iterator of byte chunks:

```python
async for chunk in store.stream_get("video.mp4"):
    yield chunk

await store.stream_put("upload.iso", chunks_iter)
```

Important for large media files where 4 GB of bytes in RAM is not
acceptable.

## Multipart uploads

Cloud drivers support multipart uploads natively. Expose them through
an explicit method (`begin_upload`, `append_chunk`, `complete_upload`)
so the local driver can simulate them and the cloud drivers can take
the fast path.

## Signed URLs

For private buckets the user wants to hand out time-limited download
links instead of routing bytes through the application. Add
`signed_url(path, expires_in=timedelta(...))`; the local driver returns
the same value as `url()`, the cloud drivers sign with their respective
SDK.

## Listing directories

`list_files(prefix, recursive=False)` returning an async iterator of
paths. Useful for batch jobs and admin tooling.

## File metadata

`metadata(path) -> FileMetadata` returning a typed record with size,
content type, last modified, and arbitrary tags supported by the
underlying driver.
