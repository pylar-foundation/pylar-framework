"""WebSocket route registration model.

WebSocket routes live alongside the HTTP routes on the same
:class:`Router`, but they carry a different shape: there is no HTTP
method, no middleware pipeline (yet — see ``docs/todo/routing.md``),
and the handler is a single-arg async callable that takes a
:class:`WebSocket`. The compiler turns each spec into a Starlette
``WebSocketRoute`` whose endpoint resolves the handler's other
parameters through the container, exactly the way HTTP handlers do.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pylar.broadcasting.socket import WebSocket

#: Anything callable that takes a :class:`WebSocket` (plus any DI extras)
#: and returns nothing.
WebSocketHandler = Callable[..., Awaitable[None]]


@dataclass(frozen=True, slots=True)
class WebSocketRouteSpec:
    """A registered WebSocket endpoint.

    Stored on the router during registration and consumed by
    :class:`RoutesCompiler` when the kernel builds the Starlette app.
    """

    path: str
    handler: WebSocketHandler
    name: str | None = None


__all__ = ["WebSocket", "WebSocketHandler", "WebSocketRouteSpec"]
