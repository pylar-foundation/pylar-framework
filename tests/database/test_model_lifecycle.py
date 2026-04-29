"""End-to-end model lifecycle tests: create, update, soft-delete, hard-delete.

Exercises the full Manager CRUD surface against an in-memory SQLite
database with two model types:

* ``Item`` — standard model (hard delete only)
* ``Article`` — model with ``TimestampsMixin`` + ``SoftDeletes``

Every test gets a fresh database and ambient session so they are
fully isolated.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Mapped, mapped_column

from pylar.database import (
    ConnectionManager,
    DatabaseConfig,
    Model,
    SoftDeletes,
    TimestampsMixin,
    use_session,
)

# ---------------------------------------------------------- test models


class Item(Model):
    """Plain model — no timestamps, no soft deletes."""

    __tablename__ = "lifecycle_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    price: Mapped[int] = mapped_column(default=0)


class Article(Model, TimestampsMixin, SoftDeletes):
    """Model with timestamps and soft deletes."""

    __tablename__ = "lifecycle_articles"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str]
    body: Mapped[str] = mapped_column(default="")
    published: Mapped[bool] = mapped_column(default=False)


# ---------------------------------------------------------- fixtures


@pytest.fixture
async def db() -> AsyncIterator[ConnectionManager]:
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
async def session(db: ConnectionManager) -> AsyncIterator[None]:
    async with use_session(db):
        yield


# ======================================================= CREATE


class TestCreate:
    async def test_create_with_defaults(self, session: None) -> None:
        """Fields with defaults are populated automatically."""
        item = Item(name="Widget")
        await Item.query.save(item)

        assert item.id is not None
        assert item.id >= 1
        assert item.name == "Widget"
        assert item.price == 0  # default

    async def test_create_with_explicit_values(self, session: None) -> None:
        item = Item(name="Gadget", price=42)
        await Item.query.save(item)

        assert item.name == "Gadget"
        assert item.price == 42

    async def test_create_populates_timestamps(self, session: None) -> None:
        """TimestampsMixin sets created_at and updated_at on insert."""
        before = datetime.now(UTC)
        article = Article(title="Hello")
        await Article.query.save(article)

        assert article.created_at is not None
        assert article.updated_at is not None
        assert article.created_at >= before
        assert article.updated_at >= before

    async def test_create_soft_delete_model_starts_untrashed(self, session: None) -> None:
        article = Article(title="Fresh")
        await Article.query.save(article)

        assert article.deleted_at is None
        assert article.trashed() is False

    async def test_created_record_retrievable_by_pk(self, session: None) -> None:
        item = Item(name="Findable")
        await Item.query.save(item)

        found = await Item.query.get(item.id)
        assert found.name == "Findable"

    async def test_create_multiple_records(self, session: None) -> None:
        for i in range(5):
            await Item.query.save(Item(name=f"Item {i}"))

        count = await Item.query.count()
        assert count == 5


# ======================================================= UPDATE


class TestUpdate:
    async def test_update_field(self, session: None) -> None:
        item = Item(name="Before")
        await Item.query.save(item)

        item.name = "After"
        await Item.query.save(item)

        reloaded = await Item.query.get(item.id)
        assert reloaded.name == "After"

    async def test_update_multiple_fields(self, session: None) -> None:
        item = Item(name="Old", price=10)
        await Item.query.save(item)

        item.name = "New"
        item.price = 99
        await Item.query.save(item)

        reloaded = await Item.query.get(item.id)
        assert reloaded.name == "New"
        assert reloaded.price == 99

    async def test_update_does_not_change_pk(self, session: None) -> None:
        item = Item(name="Stable")
        await Item.query.save(item)
        original_id = item.id

        item.name = "Changed"
        await Item.query.save(item)

        assert item.id == original_id

    async def test_update_bumps_updated_at(self, session: None) -> None:
        """TimestampsMixin bumps updated_at on UPDATE."""
        article = Article(title="V1")
        await Article.query.save(article)
        first_updated = article.updated_at

        article.title = "V2"
        await Article.query.save(article)

        # SQLAlchemy onupdate fires on flush — updated_at should advance.
        assert article.updated_at >= first_updated

    async def test_update_does_not_change_created_at(self, session: None) -> None:
        article = Article(title="Immutable created_at")
        await Article.query.save(article)
        original_created = article.created_at

        article.title = "Modified"
        await Article.query.save(article)

        assert article.created_at == original_created


# ======================================================= HARD DELETE


class TestHardDelete:
    async def test_delete_removes_record(self, session: None) -> None:
        item = Item(name="Doomed")
        await Item.query.save(item)

        await Item.query.delete(item)

        # No items should remain.
        remaining = await Item.query.count()
        assert remaining == 0

    async def test_delete_one_of_many(self, session: None) -> None:
        a = Item(name="Keep")
        b = Item(name="Remove")
        await Item.query.save(a)
        await Item.query.save(b)

        await Item.query.delete(b)

        remaining = await Item.query.count()
        assert remaining == 1
        survivor = await Item.query.first()
        assert survivor is not None
        assert survivor.name == "Keep"


# ======================================================= SOFT DELETE


class TestSoftDelete:
    async def test_soft_delete_sets_deleted_at(self, session: None) -> None:
        article = Article(title="To trash")
        await Article.query.save(article)

        await Article.query.delete(article)

        assert article.deleted_at is not None
        assert article.trashed() is True

    async def test_soft_deleted_excluded_from_default_query(self, session: None) -> None:
        """Default QuerySet hides soft-deleted rows."""
        a = Article(title="Visible")
        b = Article(title="Trashed")
        await Article.query.save(a)
        await Article.query.save(b)

        await Article.query.delete(b)

        # Default query excludes trashed.
        visible = await Article.query.all()
        assert len(visible) == 1
        assert visible[0].title == "Visible"

    async def test_with_trashed_includes_soft_deleted(self, session: None) -> None:
        a = Article(title="Alive")
        b = Article(title="Dead")
        await Article.query.save(a)
        await Article.query.save(b)
        await Article.query.delete(b)

        all_rows = await Article.query.with_trashed().all()
        assert len(all_rows) == 2

    async def test_only_trashed_returns_deleted_only(self, session: None) -> None:
        a = Article(title="Alive")
        b = Article(title="Dead")
        await Article.query.save(a)
        await Article.query.save(b)
        await Article.query.delete(b)

        trashed = await Article.query.only_trashed().all()
        assert len(trashed) == 1
        assert trashed[0].title == "Dead"

    async def test_restore_clears_deleted_at(self, session: None) -> None:
        article = Article(title="Revived")
        await Article.query.save(article)
        await Article.query.delete(article)
        assert article.trashed() is True

        await Article.query.restore(article)

        assert article.deleted_at is None
        assert article.trashed() is False

        # Should be visible in default query again.
        visible = await Article.query.all()
        assert any(a.title == "Revived" for a in visible)

    async def test_force_delete_removes_permanently(self, session: None) -> None:
        """force_delete bypasses soft-delete and physically removes the row."""
        article = Article(title="Gone forever")
        await Article.query.save(article)

        await Article.query.force_delete(article)

        # Not even with_trashed should find it.
        all_rows = await Article.query.with_trashed().all()
        assert len(all_rows) == 0

    async def test_force_delete_on_already_trashed(self, session: None) -> None:
        """force_delete works on a row that was already soft-deleted."""
        article = Article(title="Double delete")
        await Article.query.save(article)
        await Article.query.delete(article)
        assert article.trashed() is True

        await Article.query.force_delete(article)

        all_rows = await Article.query.with_trashed().all()
        assert len(all_rows) == 0

    async def test_count_excludes_soft_deleted(self, session: None) -> None:
        for i in range(3):
            await Article.query.save(Article(title=f"A{i}"))

        # Soft-delete one.
        first = await Article.query.first()
        assert first is not None
        await Article.query.delete(first)

        assert await Article.query.count() == 2

    async def test_restore_non_soft_delete_model_raises(self, session: None) -> None:
        """Restoring a hard-delete-only model raises TypeError."""
        item = Item(name="Not soft")
        await Item.query.save(item)

        with pytest.raises(TypeError, match="does not use SoftDeletes"):
            await Item.query.restore(item)
