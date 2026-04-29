"""Tests for ConnectionManager pool event listeners (REVIEW-5 B5)."""

from __future__ import annotations

from pathlib import Path

from pylar.database import ConnectionManager, DatabaseConfig


async def test_pool_listeners_installed(tmp_path: Path) -> None:
    """checkout and invalidate events have at least one listener registered."""
    url = f"sqlite+aiosqlite:///{tmp_path / 'listeners.db'}"
    mgr = ConnectionManager(DatabaseConfig(url=url))
    await mgr.initialize()
    try:
        pool = mgr.engine.sync_engine.pool
        # Pool events: checkout + invalidate. dispatch exposes each
        # event as an attribute whose .listeners list holds callables.
        assert len(pool.dispatch.checkout.listeners) >= 1
        assert len(pool.dispatch.invalidate.listeners) >= 1
    finally:
        await mgr.dispose()


async def test_checkout_listener_is_resilient_to_static_pool(
    tmp_path: Path,
) -> None:
    """In-memory SQLite uses StaticPool which lacks size()/checkedin()/overflow().

    The listener must swallow AttributeError so it doesn't break requests.
    """
    mgr = ConnectionManager(
        DatabaseConfig(url="sqlite+aiosqlite:///:memory:")
    )
    await mgr.initialize()
    try:
        async with mgr.engine.begin():
            pass  # triggers checkout event
    finally:
        await mgr.dispose()
