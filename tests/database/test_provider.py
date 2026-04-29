"""Tests for :class:`DatabaseServiceProvider` lifecycle integration."""

from __future__ import annotations

from pathlib import Path

from pylar.database import (
    ConnectionManager,
    DatabaseConfig,
    DatabaseServiceProvider,
)
from pylar.foundation import (
    AppConfig,
    Application,
    Container,
    ServiceProvider,
)


class _ConfigBindingProvider(ServiceProvider):
    """Test helper: bind a DatabaseConfig in place of the config loader."""

    def register(self, container: Container) -> None:
        container.instance(
            DatabaseConfig,
            DatabaseConfig(url="sqlite+aiosqlite:///:memory:", echo=False),
        )


def _make_app() -> Application:
    return Application(
        base_path=Path("/tmp/pylar-db-provider-test"),
        config=AppConfig(
            name="db-provider-test",
            debug=True,
            providers=(_ConfigBindingProvider, DatabaseServiceProvider),
        ),
    )


async def test_boot_initializes_engine_and_session_factory() -> None:
    app = _make_app()
    await app.bootstrap()

    manager = app.container.make(ConnectionManager)
    # Engine + factory are now reachable without raising.
    assert manager.engine is not None
    assert manager.session_factory is not None

    await app.shutdown()


async def test_shutdown_disposes_the_engine() -> None:
    app = _make_app()
    await app.bootstrap()
    manager = app.container.make(ConnectionManager)
    await app.shutdown()

    # After dispose, accessing the engine raises a RuntimeError per the
    # ConnectionManager contract.
    import pytest

    with pytest.raises(RuntimeError, match="not been initialized"):
        _ = manager.engine


async def test_connection_manager_is_singleton() -> None:
    app = _make_app()
    await app.bootstrap()
    a = app.container.make(ConnectionManager)
    b = app.container.make(ConnectionManager)
    assert a is b
    await app.shutdown()
