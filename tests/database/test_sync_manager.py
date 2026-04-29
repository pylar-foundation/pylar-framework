"""Tests for SyncManager and SyncQuerySet — the .sync façade."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from pylar.database import Model, fields
from pylar.database.config import DatabaseConfig
from pylar.database.connection import ConnectionManager
from pylar.database.session import use_session


class SyncPost(Model):
    __tablename__ = "sync_posts"
    title = fields.CharField(max_length=200)
    published = fields.BooleanField(default=False)


@pytest.fixture
async def _db() -> AsyncIterator[ConnectionManager]:
    config = DatabaseConfig(url="sqlite+aiosqlite:///:memory:")
    mgr = ConnectionManager(config)
    await mgr.initialize()
    async with mgr.engine.begin() as conn:
        await conn.run_sync(Model.metadata.create_all)
    yield mgr
    await mgr.dispose()


@pytest.fixture
async def _session(_db: ConnectionManager) -> AsyncIterator[None]:
    async with use_session(_db) as sess:
        sess.add_all([
            SyncPost(title="First", published=True),
            SyncPost(title="Second", published=False),
            SyncPost(title="Third", published=True),
        ])
        await sess.commit()
        yield


async def test_sync_all_returns_list(_session: None) -> None:
    posts = SyncPost.query.sync.all()
    assert isinstance(posts, list)
    assert len(posts) == 3


async def test_sync_first_returns_instance(_session: None) -> None:
    post = SyncPost.query.sync.first()
    assert post is not None
    assert isinstance(post, SyncPost)


async def test_sync_count(_session: None) -> None:
    assert SyncPost.query.sync.count() == 3


async def test_sync_where_chain(_session: None) -> None:
    published = SyncPost.query.sync.where(
        SyncPost.published.is_(True)  # type: ignore[attr-defined]
    ).all()
    assert len(published) == 2
    assert all(p.published for p in published)


async def test_sync_get_by_pk(_session: None) -> None:
    first = SyncPost.query.sync.first()
    assert first is not None
    fetched = SyncPost.query.sync.get(first.id)  # type: ignore[attr-defined]
    assert fetched.id == first.id  # type: ignore[attr-defined]


async def test_sync_save_writes_changes(_session: None) -> None:
    post = SyncPost.query.sync.first()
    assert post is not None
    post.title = "Updated"
    SyncPost.query.sync.save(post)

    fetched = SyncPost.query.sync.get(post.id)  # type: ignore[attr-defined]
    assert fetched.title == "Updated"


async def test_sync_from_queryset_property(_session: None) -> None:
    qs = SyncPost.query.where(
        SyncPost.published.is_(True)  # type: ignore[attr-defined]
    )
    count = qs.sync.count()
    assert count == 2


async def test_run_sync_passes_through_non_awaitable() -> None:
    from pylar.database import run_sync

    assert run_sync(42) == 42  # type: ignore[arg-type]
