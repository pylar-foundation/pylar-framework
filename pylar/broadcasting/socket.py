"""Re-exports of Starlette's WebSocket primitives.

Pylar's broadcasting layer is a thin shell around Starlette's
``WebSocket`` and ``WebSocketDisconnect`` types. Users import the names
from :mod:`pylar.broadcasting` so the framework keeps a single import
point and can extend it later (typed message bodies, automatic JSON
encoding, etc.) without breaking caller code.
"""

from __future__ import annotations

from starlette.websockets import WebSocket, WebSocketDisconnect

__all__ = ["WebSocket", "WebSocketDisconnect"]
