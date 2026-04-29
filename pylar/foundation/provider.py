"""Service providers — the only sanctioned extension point of pylar."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pylar.foundation.container import Container

if TYPE_CHECKING:
    from pylar.foundation.application import Application


class ServiceProvider:
    """Two-phase extension point for the application.

    Subclasses register their bindings synchronously in :meth:`register`. Once
    every provider in the application has finished registration, pylar enters
    the boot phase and calls :meth:`boot` on each provider in order. Side
    effects — opening database pools, attaching event listeners, populating
    the router — belong in :meth:`boot`, never in :meth:`register`.

    On shutdown providers are torn down in reverse order via :meth:`shutdown`.
    Default implementations of all three hooks are no-ops, so subclasses
    override only what they need.
    """

    def __init__(self, app: Application) -> None:
        self.app = app

    def register(self, container: Container) -> None:
        """Bind types into the container. No I/O, no cross-provider lookups."""
        return None

    async def boot(self, container: Container) -> None:
        """Perform side effects after every provider has been registered."""
        return None

    async def shutdown(self, container: Container) -> None:
        """Release any resources acquired during :meth:`boot`."""
        return None
