"""Service provider that wires migrations into the application."""

from __future__ import annotations

from pylar.console.kernel import COMMANDS_TAG
from pylar.database.config import DatabaseConfig
from pylar.database.migrations.commands import (
    MakeMigrationCommand,
    MigrateCommand,
    MigrateFreshCommand,
    MigrateRefreshCommand,
    MigrateResetCommand,
    MigrateRollbackCommand,
    MigrateStatusCommand,
    SeedCommand,
)
from pylar.database.migrations.runner import MigrationsRunner
from pylar.database.model import Model
from pylar.foundation.container import Container
from pylar.foundation.provider import ServiceProvider


class MigrationsServiceProvider(ServiceProvider):
    """Bind :class:`MigrationsRunner` and tag the migration commands.

    Listed in ``config/app.py`` after :class:`DatabaseServiceProvider`. The
    runner pulls the URL from the bound :class:`DatabaseConfig` and uses
    ``Model.metadata`` as the autogenerate target — every model that
    inherits from :class:`pylar.database.Model` is therefore visible to
    ``pylar make:migration`` automatically.

    Tagged commands: ``migrate``, ``migrate:rollback``, ``migrate:fresh``,
    ``migrate:reset``, ``migrate:status``, ``make:migration``,
    ``db:seed``.
    """

    def register(self, container: Container) -> None:
        container.singleton(MigrationsRunner, self._make_runner)
        container.tag(
            [
                MigrateCommand,
                MigrateRollbackCommand,
                MigrateFreshCommand,
                MigrateRefreshCommand,
                MigrateResetCommand,
                MigrateStatusCommand,
                MakeMigrationCommand,
                SeedCommand,
            ],
            COMMANDS_TAG,
        )

    def _make_runner(self) -> MigrationsRunner:
        config = self.app.container.make(DatabaseConfig)
        return MigrationsRunner(
            url=config.url,
            metadata=Model.metadata,
            migrations_path=self.app.base_path / "database" / "migrations",
        )
