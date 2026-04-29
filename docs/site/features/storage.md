# Storage

Pylar's storage module provides a `FilesystemStore` protocol with sandboxed local and in-memory implementations for file operations.

## Configuration

```python
from pathlib import Path
from pylar.storage import LocalStorage

storage = LocalStorage(
    root=Path("storage/app"),
    base_url="/files",  # optional — used by url()
)

# Register in the container:
container.singleton(FilesystemStore, lambda: storage)
```

## Basic Operations

```python
from pylar.storage import FilesystemStore

storage: FilesystemStore  # auto-wired

# Write a file:
await storage.put("uploads/photo.jpg", image_bytes)

# Read a file:
data = await storage.get("uploads/photo.jpg")

# Check existence:
if await storage.exists("uploads/photo.jpg"):
    size = await storage.size("uploads/photo.jpg")

# Get a URL:
url = await storage.url("uploads/photo.jpg")  # "/files/uploads/photo.jpg"

# Delete:
await storage.delete("uploads/photo.jpg")
```

## Path Sandboxing

`LocalStorage` enforces path sandboxing — all paths are resolved relative to the `root` directory. Attempts to traverse outside the root raise `PathTraversalError`:

```python
await storage.get("../../etc/passwd")  # raises PathTraversalError
await storage.get("/absolute/path")    # raises PathTraversalError
```

This is enforced on every operation, not just user-facing ones.

## FilesystemStore Protocol

Implement this protocol to add a custom backend (S3, GCS, etc.):

```python
from pylar.storage import FilesystemStore

class S3Storage:
    async def exists(self, path: str) -> bool: ...
    async def get(self, path: str) -> bytes: ...
    async def put(self, path: str, contents: bytes) -> None: ...
    async def delete(self, path: str) -> None: ...
    async def size(self, path: str) -> int: ...
    async def url(self, path: str) -> str: ...
```

## Built-in Stores

| Store | Backend | Use Case |
|---|---|---|
| `LocalStorage` | Local filesystem | Production single-server deployments |
| `MemoryStorage` | In-process dict | Testing, ephemeral data |

### MemoryStorage

```python
from pylar.storage import MemoryStorage

storage = MemoryStorage()
await storage.put("test.txt", b"hello")
assert await storage.get("test.txt") == b"hello"

url = await storage.url("test.txt")  # "memory://test.txt"
```

## Async I/O

`LocalStorage` wraps all filesystem operations via `asyncio.to_thread`, keeping the async surface consistent. No blocking I/O touches the event loop.

## Error Handling

| Exception | When |
|---|---|
| `StorageError` | Base exception for all storage errors |
| `FileNotFoundError` | File does not exist on `get()`, `size()`, `delete()` |
| `PathTraversalError` | Path escapes the root directory |
