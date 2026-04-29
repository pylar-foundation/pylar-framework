"""Exceptions raised by the storage layer."""

from __future__ import annotations


class StorageError(Exception):
    """Base class for storage errors."""


class FileNotFoundError(StorageError):
    """Raised when a requested file does not exist in the store."""

    def __init__(self, path: str) -> None:
        self.path = path
        super().__init__(f"File not found: {path}")


class PathTraversalError(StorageError):
    """Raised when a request would escape the configured storage root."""

    def __init__(self, path: str) -> None:
        self.path = path
        super().__init__(f"Path traversal attempt blocked: {path}")
