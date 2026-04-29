"""Binding records and lifetime scopes used by the container."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

#: A zero-argument factory. The container resolves the factory's own dependencies
#: by inspecting the type hints of the underlying class — factories themselves
#: take no arguments to keep the public API free of `**kwargs`.
type Factory[T] = Callable[[], T]

#: Concrete side of a binding: either a class to instantiate or a factory.
type Concrete[T] = type[T] | Factory[T]


class Scope(Enum):
    """Lifetime of an instance produced by a binding."""

    TRANSIENT = "transient"  # new instance on every resolve
    SINGLETON = "singleton"  # one instance for the lifetime of the container
    SCOPED = "scoped"        # one instance per active scope context (e.g. per request)


@dataclass(frozen=True, slots=True)
class Binding[T]:
    """A registered mapping from an abstract type to its concrete provider."""

    abstract: type[T]
    concrete: Concrete[T]
    scope: Scope
