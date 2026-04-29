"""The :class:`Route` value object."""

from __future__ import annotations

from dataclasses import dataclass

from pylar.http.middleware import Middleware
from pylar.routing.action import Action


@dataclass(frozen=True, slots=True)
class Route:
    """A single registered route.

    Routes are immutable value objects: each call to ``router.get(...)`` and
    each registration through a :class:`RouteGroup` produces a new ``Route``
    rather than mutating an existing one.
    """

    method: str
    path: str
    action: Action
    middleware: tuple[type[Middleware], ...] = ()
    name: str | None = None
