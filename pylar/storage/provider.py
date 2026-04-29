"""Service provider that wires the storage layer."""

from __future__ import annotations

from pathlib import Path

from pylar.foundation.container import Container
from pylar.foundation.provider import ServiceProvider
from pylar.storage.config import StorageConfig
from pylar.storage.drivers.local import LocalStorage
from pylar.storage.store import FilesystemStore


class StorageServiceProvider(ServiceProvider):
    """Bind a :class:`LocalStorage` driver from the user's :class:`StorageConfig`.

    The user supplies the configuration in ``config/storage.py``; the
    provider reads ``root`` and ``base_url`` from it. Production
    deployments that need cloud storage override the
    :class:`FilesystemStore` binding in their own provider.
    """

    def register(self, container: Container) -> None:
        container.singleton(FilesystemStore, self._make_local_storage)  # type: ignore[type-abstract]

    def _make_local_storage(self) -> LocalStorage:
        config = self.app.container.make(StorageConfig)
        return LocalStorage(Path(config.root), base_url=config.base_url)
