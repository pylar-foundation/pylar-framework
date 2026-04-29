"""Shared fixtures for admin tests."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from pylar_admin.config import AdminConfig
from pylar_admin.registry import AdminRegistry
from sqlalchemy.orm import Mapped, mapped_column

from pylar.database import (
    ConnectionManager,
    DatabaseConfig,
    Model,
    TimestampsMixin,
    use_session,
)


class Article(Model, TimestampsMixin):
    __tablename__ = "admin_test_articles"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str]
    body: Mapped[str]
    published: Mapped[bool] = mapped_column(default=False)


class Tag(Model):
    __tablename__ = "admin_test_tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)


@pytest.fixture
def admin_config() -> AdminConfig:
    return AdminConfig(prefix="/admin", per_page=10, require_auth=False)


@pytest.fixture
def registry() -> AdminRegistry:
    return AdminRegistry()


@pytest.fixture
async def db_manager() -> AsyncIterator[ConnectionManager]:
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
async def db_session(db_manager: ConnectionManager) -> AsyncIterator[None]:
    async with use_session(db_manager) as sess:
        sess.add_all([
            Article(title="First Post", body="Hello world", published=True),
            Article(title="Draft", body="Not ready", published=False),
            Tag(name="python"),
            Tag(name="async"),
        ])
        await sess.commit()
        yield
