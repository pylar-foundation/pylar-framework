"""Exceptions raised by the foundation layer."""

from __future__ import annotations


class ContainerError(Exception):
    """Base class for all container-related errors."""


class BindingError(ContainerError):
    """Raised when a requested abstract has no binding and cannot be auto-built."""


class ResolutionError(ContainerError):
    """Raised when a class or callable cannot be auto-wired."""


class CircularDependencyError(ContainerError):
    """Raised when the resolver detects a cycle in the dependency graph."""

    def __init__(self, chain: list[type]) -> None:
        self.chain = chain
        rendered = " -> ".join(cls.__qualname__ for cls in chain)
        super().__init__(f"Circular dependency detected: {rendered}")
