"""Named cache stores — Laravel-style :class:`CacheManager`.

The manager lets applications use multiple cache backends
simultaneously — for example an in-memory store for hot process-local
data alongside a shared Redis store for cross-instance coordination::

    # config/cache.py
    from pylar.cache import CacheConfig

    config = CacheConfig(
        default="redis",
        stores={
            "redis": {"driver": "redis", "url": "redis://localhost:6379/0"},
            "array": {"driver": "memory"},
            "file":  {"driver": "file", "path": "storage/cache"},
        },
    )

    # In a controller or service:
    cache = container.make(CacheManager)

    # Default store (redis):
    await cache.store().put("key", "value", ttl=60)

    # Named store:
    await cache.store("array").put("hot", "data")

Each ``store()`` call returns a fully-featured :class:`Cache` instance
with tagging, locking, atomic counters, and everything else the
facade offers. Stores are created lazily on first access and cached
for the lifetime of the manager.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pylar.cache.cache import Cache
from pylar.cache.store import CacheStore


class CacheManager:
    """Resolve named :class:`Cache` instances from a configuration dict.

    The manager owns the mapping ``{name: Cache}`` and creates stores
    lazily on first access. Once created a store is reused for the
    lifetime of the manager (singleton per name).

    The ``stores`` dict uses the same shape as Laravel::

        {
            "redis": {"driver": "redis", "url": "redis://localhost:6379/0", "prefix": "app:"},
            "array": {"driver": "memory"},
            "file":  {"driver": "file", "path": "storage/cache"},
        }

    Drivers that need container-managed dependencies (like
    ``DatabaseCacheStore`` which requires the application's
    ``AsyncEngine``) can be pre-registered via :meth:`extend`.
    """

    def __init__(
        self,
        *,
        default: str = "memory",
        stores: dict[str, dict[str, Any]] | None = None,
        base_path: Path | None = None,
    ) -> None:
        self._default = default
        self._stores_config = stores or {"memory": {"driver": "memory"}}
        self._base_path = base_path
        self._resolved: dict[str, Cache] = {}
        self._custom_drivers: dict[str, Any] = {}

    @property
    def default_store(self) -> str:
        """Name of the default store."""
        return self._default

    def store(self, name: str | None = None) -> Cache:
        """Return the :class:`Cache` for the named store.

        If *name* is ``None`` the default store is returned. Stores
        are created lazily on first access and cached for reuse.
        """
        resolved_name = name or self._default
        if resolved_name in self._resolved:
            return self._resolved[resolved_name]

        if resolved_name not in self._stores_config:
            raise KeyError(
                f"Cache store {resolved_name!r} is not configured. "
                f"Available: {sorted(self._stores_config)}"
            )

        config = self._stores_config[resolved_name]
        driver = self._make_driver(resolved_name, config)
        cache = Cache(driver)
        self._resolved[resolved_name] = cache
        return cache

    def extend(self, driver_name: str, factory: Any) -> None:
        """Register a custom driver factory.

        *factory* is a callable that receives the config dict and
        returns a :class:`CacheStore`::

            manager.extend("dynamodb", lambda cfg: DynamoStore(cfg["table"]))
        """
        self._custom_drivers[driver_name] = factory

    def _make_driver(self, name: str, config: dict[str, Any]) -> CacheStore:
        """Instantiate a :class:`CacheStore` from a config dict."""
        driver_name = config.get("driver", name)

        # Custom drivers registered via extend() take priority.
        if driver_name in self._custom_drivers:
            return self._custom_drivers[driver_name](config)  # type: ignore[no-any-return]

        if driver_name in ("memory", "array"):
            from pylar.cache.drivers.memory import MemoryCacheStore

            return MemoryCacheStore()

        if driver_name == "file":
            from pylar.cache.drivers.file import FileCacheStore

            path = config.get("path", "storage/cache")
            root = self._base_path / path if self._base_path else Path(path)
            return FileCacheStore(root)

        if driver_name == "redis":
            from pylar.cache.drivers.redis import RedisCacheStore

            try:
                from redis.asyncio import Redis
            except ImportError:
                raise ImportError(
                    "Redis cache store requires the 'redis' package. "
                    "Install with: pip install 'pylar[cache-redis]'"
                ) from None

            url = config.get("url", "redis://localhost:6379/0")
            prefix = config.get("prefix", "pylar:cache:")
            client = Redis.from_url(url)
            return RedisCacheStore(client, prefix=prefix)

        raise ValueError(
            f"Unknown cache driver {driver_name!r} for store {name!r}. "
            f"Supported: memory, array, file, redis (or register via extend())"
        )

    def purge(self, name: str | None = None) -> None:
        """Drop a resolved store so the next ``store()`` call recreates it.

        Without *name*, purge all resolved stores. Useful after config
        changes or in tests.
        """
        if name is None:
            self._resolved.clear()
        else:
            self._resolved.pop(name, None)

    async def flush_all(self) -> None:
        """Flush every resolved store."""
        for cache in self._resolved.values():
            await cache.flush()
