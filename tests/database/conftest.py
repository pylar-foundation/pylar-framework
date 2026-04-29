"""Shared fixtures for database tests — an aiosqlite in-memory schema."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy.orm import Mapped, mapped_column

from pylar.database import (
    ConnectionManager,
    DatabaseConfig,
    Model,
    use_session,
)


class User(Model):
    __tablename__ = "test_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(unique=True)
    name: Mapped[str]
    active: Mapped[bool] = mapped_column(default=True)


@pytest.fixture
async def manager() -> AsyncIterator[ConnectionManager]:
    config = DatabaseConfig(url="sqlite+aiosqlite:///:memory:", echo=False)
    mgr = ConnectionManager(config)
    await mgr.initialize()
    async with mgr.engine.begin() as conn:
        await conn.run_sync(Model.metadata.create_all)
    try:
        yield mgr
    finally:
        await mgr.dispose()


@pytest.fixture
async def session(manager: ConnectionManager) -> AsyncIterator[None]:
    """Open an ambient session for the duration of one test, with seed data."""
    async with use_session(manager) as sess:
        sess.add_all([
            User(email="alice@example.com", name="Alice", active=True),
            User(email="bob@example.com", name="Bob", active=True),
            User(email="charlie@example.com", name="Charlie", active=False),
        ])
        await sess.commit()
        yield
