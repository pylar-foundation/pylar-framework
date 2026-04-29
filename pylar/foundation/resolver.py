"""Constructor and callable introspection for the container's auto-wiring."""

from __future__ import annotations

import inspect
import typing
from collections.abc import Callable
from dataclasses import dataclass
from inspect import Parameter
from typing import Any, get_type_hints

from pylar.foundation.exceptions import ResolutionError


@dataclass(frozen=True, slots=True)
class ResolvedParameter:
    """A single parameter ready to be filled by the container."""

    name: str
    annotation: type[Any] | None  # None means "use default"
    default: object  # Parameter.empty when no default
    has_default: bool


def inspect_callable(
    target: Callable[..., Any],
    *,
    owner: object | None = None,
) -> list[ResolvedParameter]:
    """Return the list of parameters of *target* annotated with their types.

    Forbids ``*args`` and ``**kwargs`` — pylar's public APIs must be explicit.
    Raises :class:`ResolutionError` for any parameter that lacks a type hint
    and has no default value.
    """
    try:
        signature = inspect.signature(target)
    except (TypeError, ValueError) as exc:  # pragma: no cover - exotic callables
        raise ResolutionError(f"{_qualname(target)} is not introspectable: {exc}") from exc

    hints = _safe_get_type_hints(target)
    resolved: list[ResolvedParameter] = []

    for name, param in signature.parameters.items():
        if name == "self" or name == "cls":
            continue

        if param.kind is Parameter.VAR_POSITIONAL:
            raise ResolutionError(
                f"{_qualname(target)} declares *{name} — "
                "variadic positionals are forbidden in pylar"
            )
        if param.kind is Parameter.VAR_KEYWORD:
            raise ResolutionError(
                f"{_qualname(target)} declares **{name} — variadic keywords are forbidden in pylar"
            )

        annotation = hints.get(name)
        has_default = param.default is not Parameter.empty

        if annotation in (Any, object, typing.Any):
            annotation = None

        if annotation is None and not has_default:
            raise ResolutionError(
                f"{_qualname(target)} parameter '{name}' has no type hint and no default — "
                f"cannot auto-wire"
            )

        resolved.append(
            ResolvedParameter(
                name=name,
                annotation=annotation,
                default=param.default if has_default else None,
                has_default=has_default,
            )
        )

    return resolved


def _safe_get_type_hints(target: Callable[..., Any]) -> dict[str, type[Any]]:
    try:
        return get_type_hints(target)
    except Exception:
        # Fall back to raw annotations; the resolver will then fail per-parameter
        # with a precise error message.
        return getattr(target, "__annotations__", {}) or {}


def _qualname(target: Callable[..., Any]) -> str:
    return getattr(target, "__qualname__", repr(target))
