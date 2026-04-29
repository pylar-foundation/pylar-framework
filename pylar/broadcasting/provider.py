"""Service provider that wires the broadcasting layer."""

from __future__ import annotations

from pylar.broadcasting.broadcaster import Broadcaster
from pylar.broadcasting.drivers.memory import MemoryBroadcaster
from pylar.foundation.container import Container
from pylar.foundation.provider import ServiceProvider


class BroadcastingServiceProvider(ServiceProvider):
    """Bind a default in-process :class:`Broadcaster`.

    Production deployments override the binding in their own provider
    when they need cross-process fan-out — typically pointing it at a
    Redis-backed driver. The WebSocket route compiler does not depend
    on the driver class directly; it injects whatever is bound to
    :class:`Broadcaster` into handler signatures via the container's
    auto-wiring.
    """

    def register(self, container: Container) -> None:
        container.singleton(Broadcaster, MemoryBroadcaster)  # type: ignore[type-abstract]
