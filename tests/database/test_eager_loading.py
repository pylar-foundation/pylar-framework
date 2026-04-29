"""Tests for ``QuerySet.with_`` eager-loading helpers."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pylar.database import (
    ConnectionManager,
    DatabaseConfig,
    Model,
    use_session,
)


class EagerAuthor(Model):
    __tablename__ = "test_eager_authors"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]

    posts: Mapped[list[EagerPost]] = relationship(
        back_populates="author", lazy="raise"
    )


class EagerTag(Model):
    __tablename__ = "test_eager_tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str]
    post_id: Mapped[int] = mapped_column(ForeignKey("test_eager_posts.id"))

    post: Mapped[EagerPost] = relationship(back_populates="tags", lazy="raise")


class EagerPost(Model):
    __tablename__ = "test_eager_posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str]
    author_id: Mapped[int] = mapped_column(ForeignKey("test_eager_authors.id"))

    author: Mapped[EagerAuthor] = relationship(back_populates="posts", lazy="raise")
    tags: Mapped[list[EagerTag]] = relationship(back_populates="post", lazy="raise")


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
    async with use_session(manager) as sess:
        a = EagerAuthor(name="Ada")
        b = EagerAuthor(name="Bea")
        sess.add_all([a, b])
        await sess.flush()
        sess.add_all([
            EagerPost(title="Hello", author_id=a.id),
            EagerPost(title="World", author_id=a.id),
            EagerPost(title="Other", author_id=b.id),
        ])
        await sess.flush()
        posts = (await sess.execute(EagerPost.__table__.select())).all()
        for row in posts:
            sess.add(EagerTag(label=f"t-{row.title}", post_id=row.id))
        await sess.commit()
        yield


pytestmark = pytest.mark.usefixtures("session")


async def test_with_loads_a_single_relationship() -> None:
    posts = await EagerPost.query.with_("author").all()
    # `lazy="raise"` would explode on attribute access if the eager
    # loader had not actually attached the related row.
    assert {p.author.name for p in posts} == {"Ada", "Bea"}


async def test_with_loads_multiple_relationships() -> None:
    posts = await EagerPost.query.with_("author", "tags").all()
    assert {p.author.name for p in posts} == {"Ada", "Bea"}
    assert all(len(p.tags) == 1 for p in posts)


async def test_with_supports_dotted_nested_paths() -> None:
    tags = await EagerTag.query.with_("post.author").all()
    assert {t.post.author.name for t in tags} == {"Ada", "Bea"}


async def test_with_chains_accumulate() -> None:
    qs = EagerPost.query.with_("author").with_("tags")
    posts = await qs.all()
    assert all(p.author is not None for p in posts)
    assert all(len(p.tags) == 1 for p in posts)


async def test_with_rejects_unknown_relationship() -> None:
    with pytest.raises(AttributeError, match="ghost"):
        await EagerPost.query.with_("ghost").all()


async def test_with_rejects_unknown_nested_relationship() -> None:
    with pytest.raises(AttributeError, match="ghost"):
        await EagerPost.query.with_("author.ghost").all()


async def test_with_rejects_empty_path() -> None:
    with pytest.raises(ValueError, match="empty relationship"):
        EagerPost.query.with_("")
