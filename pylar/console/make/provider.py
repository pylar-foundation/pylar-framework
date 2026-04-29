"""Service provider that tags every ``make:*`` command into the console."""

from __future__ import annotations

from pylar.console.kernel import COMMANDS_TAG
from pylar.console.make.commands import ALL_MAKE_COMMANDS
from pylar.foundation.container import Container
from pylar.foundation.provider import ServiceProvider


class MakeServiceProvider(ServiceProvider):
    """Register every bundled scaffolding command in one shot.

    User projects list this provider in ``config/app.py`` to expose the
    full ``pylar make:*`` family. Projects that only want a subset can
    omit this provider and tag the desired commands manually inside
    their own console service provider.
    """

    def register(self, container: Container) -> None:
        container.tag(list(ALL_MAKE_COMMANDS), COMMANDS_TAG)
