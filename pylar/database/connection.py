"""Async engine + session factory bound to a :class:`DatabaseConfig`."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from pylar.database.config import DatabaseConfig

_logger = logging.getLogger("pylar.database")


class ConnectionManager:
    """Owns the application's :class:`AsyncEngine` and session factory.

    The manager is registered as a singleton by :class:`DatabaseServiceProvider`
    and torn down on application shutdown. It exposes a :meth:`session` factory
    that downstream code (middleware, transaction helper, tests) uses to open
    short-lived sessions.
    """

    def __init__(self, config: DatabaseConfig) -> None:
        self._config = config
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    @property
    def config(self) -> DatabaseConfig:
        return self._config

    @property
    def engine(self) -> AsyncEngine:
        if self._engine is None:
            raise RuntimeError(
                "ConnectionManager has not been initialized — call `await initialize()` first."
            )
        return self._engine

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        if self._session_factory is None:
            raise RuntimeError(
                "ConnectionManager has not been initialized — call `await initialize()` first."
            )
        return self._session_factory

    async def initialize(self) -> None:
        """Build the engine and session factory.

        Called from ``DatabaseServiceProvider.boot``. Splitting initialization
        from ``__init__`` keeps the constructor side-effect free, which is
        important because the container builds the manager as part of plain
        bindings.
        """
        if self._engine is not None:
            return

        engine_kwargs: dict[str, object] = {"echo": self._config.echo}
        if not self._config.url.startswith("sqlite"):
            engine_kwargs["pool_size"] = self._config.pool_size
            engine_kwargs["max_overflow"] = self._config.max_overflow
            engine_kwargs["pool_recycle"] = self._config.pool_recycle
            engine_kwargs["pool_timeout"] = self._config.pool_timeout
            engine_kwargs["pool_pre_ping"] = True

        connect_args: dict[str, object] = {}
        if "asyncpg" in self._config.url:
            connect_args["command_timeout"] = self._config.query_timeout
        if connect_args:
            engine_kwargs["connect_args"] = connect_args

        self._engine = create_async_engine(self._config.url, **engine_kwargs)
        self._install_pool_listeners(self._engine)
        self._session_factory = async_sessionmaker(
            bind=self._engine,
            expire_on_commit=False,
            autoflush=False,
        )

    async def dispose(self) -> None:
        """Close the engine and release pooled connections."""
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None

    def session(self) -> AsyncSession:
        """Return a fresh :class:`AsyncSession`. Caller owns its lifecycle."""
        return self.session_factory()

    @staticmethod
    def _install_pool_listeners(engine: AsyncEngine) -> None:
        """Attach SQLAlchemy pool event listeners for observability."""
        from sqlalchemy import event

        sync_engine = engine.sync_engine

        @event.listens_for(sync_engine, "checkout")
        def _on_checkout(
            dbapi_conn: Any, connection_record: Any, connection_proxy: Any
        ) -> None:
            pool: Any = sync_engine.pool
            try:
                _logger.debug(
                    "Pool checkout: size=%s, checked_in=%s, overflow=%s",
                    pool.size(),
                    pool.checkedin(),
                    pool.overflow(),
                )
            except AttributeError:
                pass  # StaticPool (SQLite) has no size/checkedin/overflow

        @event.listens_for(sync_engine, "invalidate")
        def _on_invalidate(
            dbapi_conn: Any, connection_record: Any, exception: Any
        ) -> None:
            _logger.warning(
                "Connection invalidated: %s",
                type(exception).__name__ if exception else "soft invalidation",
            )
