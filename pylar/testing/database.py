"""Database helpers for tests — transactional rollback boundaries."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from pylar.database.config import DatabaseConfig
from pylar.database.connection import ConnectionManager
from pylar.database.model import Model
from pylar.database.session import override_session


async def bootstrap_schema(manager: ConnectionManager) -> None:
    """Run ``Model.metadata.create_all`` against *manager*'s engine.

    Convenience for tests that do not want to drive Alembic from
    inside the suite. The fixture pattern is::

        @pytest.fixture
        async def manager() -> AsyncIterator[ConnectionManager]:
            mgr = ConnectionManager(
                DatabaseConfig(url="sqlite+aiosqlite:///:memory:")
            )
            await mgr.initialize()
            await bootstrap_schema(mgr)
            try:
                yield mgr
            finally:
                await mgr.dispose()
    """
    async with manager.engine.begin() as conn:
        await conn.run_sync(Model.metadata.create_all)


@asynccontextmanager
async def in_memory_manager() -> AsyncIterator[ConnectionManager]:
    """Stand up a fresh in-memory aiosqlite manager for the duration of one test.

    Wraps :func:`bootstrap_schema` so the every-test boilerplate
    collapses to a single ``async with`` block::

        async def test_thing():
            async with in_memory_manager() as mgr:
                async with transactional_session(mgr):
                    ...

    For pytest fixtures use the ``pylar_db_manager`` fixture from the
    bundled plugin instead — it does the same thing but yields the
    manager so other fixtures can depend on it.
    """
    manager = ConnectionManager(
        DatabaseConfig(url="sqlite+aiosqlite:///:memory:", echo=False)
    )
    await manager.initialize()
    try:
        await bootstrap_schema(manager)
        yield manager
    finally:
        await manager.dispose()


@asynccontextmanager
async def transactional_session(
    manager: ConnectionManager,
) -> AsyncIterator[AsyncSession]:
    """Open an ambient session and roll it back on exit.

    Useful for test fixtures that want every test to start from the
    same database state. Each test runs inside the yielded session,
    and any writes are discarded when the context manager exits, so
    the next test sees only the seed data the fixture inserted.

    Pair with the conftest fixture::

        @pytest.fixture
        async def session(manager):
            async with transactional_session(manager):
                yield
    """
    session = manager.session()
    async with override_session(session):
        try:
            yield session
        finally:
            await session.rollback()
            await session.close()
