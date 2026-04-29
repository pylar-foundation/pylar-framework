"""Service provider wiring the observability layer (ADR-0008)."""

from __future__ import annotations

from pylar.console.kernel import COMMANDS_TAG
from pylar.foundation.container import Container
from pylar.foundation.provider import ServiceProvider
from pylar.observability.commands import AboutCommand
from pylar.observability.doctor import DoctorCommand


class ObservabilityServiceProvider(ServiceProvider):
    """Register the ``about`` and ``doctor`` commands.

    When the application runs in production mode (``debug=False``),
    the provider auto-installs structured JSON logging so log
    aggregators can parse every line without configuration.
    """

    def register(self, container: Container) -> None:
        container.tag([AboutCommand, DoctorCommand], COMMANDS_TAG)

    async def boot(self, container: Container) -> None:
        if not self.app.config.debug:
            from pylar.observability.logging import install_json_logging

            install_json_logging()
