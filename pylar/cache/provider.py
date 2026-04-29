"""Service provider that wires the cache layer."""

from __future__ import annotations

import importlib

from pylar.cache.cache import Cache
from pylar.cache.commands import CacheClearCommand
from pylar.cache.config import CacheConfig
from pylar.cache.drivers.memory import MemoryCacheStore
from pylar.cache.manager import CacheManager
from pylar.cache.store import CacheStore
from pylar.console.kernel import COMMANDS_TAG
from pylar.foundation.container import Container
from pylar.foundation.provider import ServiceProvider


class CacheServiceProvider(ServiceProvider):
    """Bind the cache layer — :class:`CacheManager` and default :class:`Cache`.

    When a ``config/cache.py`` module with a :class:`CacheConfig` is
    present, the provider builds a :class:`CacheManager` with named
    stores. The default :class:`Cache` singleton resolves to the
    manager's default store so existing code that depends on ``Cache``
    keeps working without changes.

    Without a config file the provider falls back to a single
    in-memory store, matching the previous behaviour.
    """

    def register(self, container: Container) -> None:
        config = self._load_config()
        if config is not None:
            manager = CacheManager(
                default=config.default,
                stores=config.stores,
                base_path=self.app.base_path,
            )
            container.singleton(CacheManager, lambda: manager)
            container.singleton(Cache, lambda: manager.store())
            container.singleton(
                CacheStore, lambda: manager.store()._store  # type: ignore[type-abstract]
            )
        else:
            container.singleton(CacheStore, MemoryCacheStore)  # type: ignore[type-abstract]
            container.singleton(Cache, self._make_cache)
        container.tag([CacheClearCommand], COMMANDS_TAG)

    def _make_cache(self) -> Cache:
        store = self.app.container.make(CacheStore)  # type: ignore[type-abstract]
        return Cache(store)

    @staticmethod
    def _load_config() -> CacheConfig | None:
        """Try to load config/cache.py from the project."""
        try:
            module = importlib.import_module("config.cache")
            config = getattr(module, "config", None)
            if isinstance(config, CacheConfig):
                return config
        except (ImportError, ModuleNotFoundError):
            pass
        return None
