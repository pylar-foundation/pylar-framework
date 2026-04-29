"""Service provider that wires HTTP-layer console commands."""

from __future__ import annotations

from pylar.console.kernel import COMMANDS_TAG
from pylar.foundation.container import Container
from pylar.foundation.provider import ServiceProvider
from pylar.http.commands import DevCommand, ServeCommand
from pylar.http.maintenance_commands import DownCommand, UpCommand
from pylar.routing.commands import RouteListCommand


class HttpServiceProvider(ServiceProvider):
    """Tag HTTP-layer console commands.

    Listed in ``config/app.py`` so that ``pylar serve``, ``pylar down``,
    ``pylar up``, and ``pylar route:list`` become available.
    """

    def register(self, container: Container) -> None:
        container.tag(
            [ServeCommand, DevCommand, DownCommand, UpCommand, RouteListCommand],
            COMMANDS_TAG,
        )
