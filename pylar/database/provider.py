"""Service provider that wires the database layer into an :class:`Application`."""

from __future__ import annotations

from pylar.database.config import DatabaseConfig
from pylar.database.connection import ConnectionManager
from pylar.foundation.container import Container
from pylar.foundation.provider import ServiceProvider


class DatabaseServiceProvider(ServiceProvider):
    """Bind a :class:`ConnectionManager` and manage its lifecycle.

    Listed in ``config/app.py`` after the user has provided a
    :class:`DatabaseConfig` instance via ``config/database.py``. The provider
    constructs the manager during ``register``, opens the engine in ``boot``,
    and disposes it in ``shutdown``.
    """

    def register(self, container: Container) -> None:
        container.singleton(ConnectionManager, self._make_manager)

    def _make_manager(self) -> ConnectionManager:
        config = self.app.container.make(DatabaseConfig)
        return ConnectionManager(config)

    async def boot(self, container: Container) -> None:
        manager = container.make(ConnectionManager)
        await manager.initialize()

    async def shutdown(self, container: Container) -> None:
        manager = container.make(ConnectionManager)
        await manager.dispose()
