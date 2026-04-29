"""Tests for relationship fields — BelongsTo, HasMany, HasOne."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from pylar.database import Model, fields
from pylar.database.config import DatabaseConfig
from pylar.database.connection import ConnectionManager
from pylar.database.session import use_session

# ----------------------------------------------------------------- models
# Use unique prefixed names to avoid conflicts with other test modules
# that also define models in the shared SA registry.


class RelAuthor(Model):
    __tablename__ = "rel_authors"
    name = fields.CharField(max_length=100)
    posts = fields.HasMany(model="RelArticle", back_populates="author")
    profile = fields.HasOne(model="RelProfile", back_populates="author")


class RelArticle(Model):
    __tablename__ = "rel_articles"
    title = fields.CharField(max_length=200)
    author = fields.BelongsTo(
        to="rel_authors.id",
        model="RelAuthor",
        on_delete="CASCADE",
        back_populates="posts",
    )


class RelProfile(Model):
    __tablename__ = "rel_profiles"
    bio = fields.TextField(null=True)
    author = fields.BelongsTo(
        to="rel_authors.id",
        model="RelAuthor",
        on_delete="CASCADE",
        back_populates="profile",
    )


# ----------------------------------------------------------------- fixtures


@pytest.fixture
async def manager() -> AsyncIterator[ConnectionManager]:
    config = DatabaseConfig(url="sqlite+aiosqlite:///:memory:")
    mgr = ConnectionManager(config)
    await mgr.initialize()
    async with mgr.engine.begin() as conn:
        await conn.run_sync(Model.metadata.create_all)
    yield mgr
    await mgr.dispose()


@pytest.fixture
async def session(manager: ConnectionManager) -> AsyncIterator[AsyncSession]:
    async with use_session(manager) as s:
        yield s


# ----------------------------------------------------------------- tests


async def test_belongs_to_creates_fk_column(session: AsyncSession) -> None:
    """BelongsTo should create both the FK column and the relationship."""
    author = RelAuthor(name="Alice")
    session.add(author)
    await session.flush()

    article = RelArticle(title="Hello", author_id=author.id)
    session.add(article)
    await session.flush()

    assert article.author_id == author.id


async def test_has_many_loads_children(session: AsyncSession) -> None:
    """HasMany relationship should allow eager-loading children."""
    author = RelAuthor(name="Bob")
    session.add(author)
    await session.flush()

    a1 = RelArticle(title="Post 1", author_id=author.id)
    a2 = RelArticle(title="Post 2", author_id=author.id)
    session.add_all([a1, a2])
    await session.flush()

    loaded = await RelAuthor.query.with_("posts").where(
        RelAuthor.id == author.id  # type: ignore[attr-defined]
    ).first(session=session)
    assert loaded is not None
    assert len(loaded.posts) == 2
    assert {a.title for a in loaded.posts} == {"Post 1", "Post 2"}


async def test_has_one_loads_single_child(session: AsyncSession) -> None:
    """HasOne relationship should load a single related object."""
    author = RelAuthor(name="Charlie")
    session.add(author)
    await session.flush()

    profile = RelProfile(bio="Hello world", author_id=author.id)
    session.add(profile)
    await session.flush()

    loaded = await RelAuthor.query.with_("profile").where(
        RelAuthor.id == author.id  # type: ignore[attr-defined]
    ).first(session=session)
    assert loaded is not None
    assert loaded.profile is not None
    assert loaded.profile.bio == "Hello world"


async def test_belongs_to_navigates_to_parent(session: AsyncSession) -> None:
    """BelongsTo should allow navigating from child to parent."""
    author = RelAuthor(name="Diana")
    session.add(author)
    await session.flush()

    article = RelArticle(title="My Post", author_id=author.id)
    session.add(article)
    await session.flush()

    loaded = await RelArticle.query.with_("author").where(
        RelArticle.id == article.id  # type: ignore[attr-defined]
    ).first(session=session)
    assert loaded is not None
    assert loaded.author is not None
    assert loaded.author.name == "Diana"


async def test_belongs_to_nullable(session: AsyncSession) -> None:
    """BelongsTo with null=True should allow nullable FK."""
    author = RelAuthor(name="Eve")
    session.add(author)
    await session.flush()

    profile = RelProfile(bio=None, author_id=author.id)
    session.add(profile)
    await session.flush()
    assert profile.author_id == author.id
