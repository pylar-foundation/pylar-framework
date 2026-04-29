"""Exceptions raised by the make: generators."""

from __future__ import annotations


class MakeError(Exception):
    """Base class for code-generation errors."""


class InvalidNameError(MakeError):
    """Raised when the supplied class name fails the PascalCase check."""


class TargetExistsError(MakeError):
    """Raised when the target file already exists and ``--force`` was not given."""

    def __init__(self, path: object) -> None:
        self.path = path
        super().__init__(f"{path} already exists. Use --force to overwrite.")
