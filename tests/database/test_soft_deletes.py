"""Behavioural tests for the :class:`SoftDeletes` mixin.

The tests use a dedicated SQLAlchemy ``MetaData`` so that they do not
interfere with the ``test_users`` table from ``conftest.py``. Each test
runs against a fresh aiosqlite in-memory database, with the schema
created via ``Model.metadata.create_all``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime

import pytest
from sqlalchemy.orm import Mapped, mapped_column

from pylar.database import (
    ConnectionManager,
    DatabaseConfig,
    Model,
    Observer,
    SoftDeletes,
    transaction,
    use_session,
)

# --------------------------------------------------------------------- domain


class Document(Model, SoftDeletes):
    __tablename__ = "test_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str]


class HardModel(Model):
    """Plain model — used to verify SoftDeletes does not bleed into others."""

    __tablename__ = "test_hard_models"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]


# ----------------------------------------------------------------- fixtures


@pytest.fixture
async def manager() -> AsyncIterator[ConnectionManager]:
    config = DatabaseConfig(url="sqlite+aiosqlite:///:memory:")
    mgr = ConnectionManager(config)
    await mgr.initialize()
    async with mgr.engine.begin() as conn:
        await conn.run_sync(Model.metadata.create_all)
    try:
        yield mgr
    finally:
        await mgr.dispose()


@pytest.fixture(autouse=True)
def _reset_observers() -> None:
    Document._observers = []  # type: ignore[attr-defined]


@pytest.fixture
async def session(manager: ConnectionManager) -> AsyncIterator[None]:
    async with use_session(manager):
        async with transaction():
            session_val = manager.session  # ensure import quiet
            del session_val
        yield


@pytest.fixture
async def seeded_session(manager: ConnectionManager) -> AsyncIterator[None]:
    async with use_session(manager):
        async with transaction():
            await Document.query.save(Document(title="alpha"))
            await Document.query.save(Document(title="beta"))
            await Document.query.save(Document(title="gamma"))
        yield


# ----------------------------------------------------------------- mixin


def test_softdeletes_adds_deleted_at_column() -> None:
    columns = {col.name for col in Document.__table__.columns}
    assert "deleted_at" in columns
    assert "title" in columns


def test_trashed_returns_false_for_fresh_instance() -> None:
    doc = Document(title="x")
    assert doc.trashed() is False


def test_hard_model_does_not_inherit_soft_delete_column() -> None:
    columns = {col.name for col in HardModel.__table__.columns}
    assert "deleted_at" not in columns


# --------------------------------------------------------- single-row delete


pytestmark = pytest.mark.usefixtures("seeded_session")


async def test_manager_delete_marks_deleted_at(manager: ConnectionManager) -> None:
    target = await Document.query.where(Document.title == "alpha").first()
    assert target is not None
    assert target.deleted_at is None

    async with transaction():
        await Document.query.delete(target)

    assert isinstance(target.deleted_at, datetime)
    assert target.trashed() is True


async def test_default_query_excludes_trashed() -> None:
    target = await Document.query.where(Document.title == "alpha").first()
    assert target is not None
    async with transaction():
        await Document.query.delete(target)

    visible = await Document.query.all()
    titles = {doc.title for doc in visible}
    assert titles == {"beta", "gamma"}


async def test_with_trashed_returns_everything() -> None:
    target = await Document.query.where(Document.title == "alpha").first()
    assert target is not None
    async with transaction():
        await Document.query.delete(target)

    everyone = await Document.query.with_trashed().all()
    assert len(everyone) == 3
    assert "alpha" in {d.title for d in everyone}


async def test_only_trashed_returns_just_the_dead() -> None:
    target = await Document.query.where(Document.title == "alpha").first()
    assert target is not None
    async with transaction():
        await Document.query.delete(target)

    dead = await Document.query.only_trashed().all()
    assert [d.title for d in dead] == ["alpha"]


async def test_count_respects_default_exclusion() -> None:
    target = await Document.query.where(Document.title == "alpha").first()
    assert target is not None
    async with transaction():
        await Document.query.delete(target)

    assert await Document.query.count() == 2
    assert await Document.query.with_trashed().count() == 3
    assert await Document.query.only_trashed().count() == 1


async def test_chain_with_where_then_with_trashed() -> None:
    """The trashed-mode flag survives chained ``where`` calls."""
    target = await Document.query.where(Document.title == "alpha").first()
    assert target is not None
    async with transaction():
        await Document.query.delete(target)

    # Default chain hides alpha even with an extra where.
    visible = await Document.query.where(Document.title.like("%a%")).all()
    assert {d.title for d in visible} == {"beta", "gamma"}

    # with_trashed brings it back, the where still applies.
    inclusive = await (
        Document.query.where(Document.title.like("%a%")).with_trashed().all()
    )
    assert {d.title for d in inclusive} == {"alpha", "beta", "gamma"}


# --------------------------------------------------------------- restore


async def test_restore_clears_deleted_at() -> None:
    target = await Document.query.where(Document.title == "alpha").first()
    assert target is not None
    async with transaction():
        await Document.query.delete(target)
    assert target.trashed()

    async with transaction():
        await Document.query.restore(target)
    assert target.deleted_at is None
    assert not target.trashed()

    titles = {d.title for d in await Document.query.all()}
    assert "alpha" in titles  # back in the default chain


async def test_restore_on_hard_model_raises(manager: ConnectionManager) -> None:
    async with use_session(manager):
        async with transaction():
            instance = HardModel(name="ephemeral")
            await HardModel.query.save(instance)

        with pytest.raises(TypeError, match="does not use SoftDeletes"):
            async with transaction():
                await HardModel.query.restore(instance)


# --------------------------------------------------------- force_delete


async def test_force_delete_actually_removes_row(manager: ConnectionManager) -> None:
    target = await Document.query.where(Document.title == "alpha").first()
    assert target is not None

    async with transaction():
        await Document.query.force_delete(target)

    # Even with_trashed cannot find it.
    assert await Document.query.with_trashed().count() == 2


async def test_force_delete_after_soft_delete() -> None:
    target = await Document.query.where(Document.title == "alpha").first()
    assert target is not None
    async with transaction():
        await Document.query.delete(target)  # tombstone first
        await Document.query.force_delete(target)  # then permanent

    assert await Document.query.with_trashed().count() == 2


# ---------------------------------------------------------- bulk QuerySet


async def test_bulk_queryset_delete_is_soft() -> None:
    async with transaction():
        await Document.query.where(Document.title == "alpha").delete()

    # Row still exists when we look at the trashed pool.
    assert await Document.query.count() == 2
    assert await Document.query.with_trashed().count() == 3


async def test_bulk_queryset_force_delete_is_hard() -> None:
    async with transaction():
        await Document.query.where(Document.title == "alpha").force_delete()

    assert await Document.query.with_trashed().count() == 2


# --------------------------------------------------------- observer hooks


class _Recorder(Observer[Document]):
    def __init__(self) -> None:
        self.events: list[str] = []

    async def deleting(self, instance: Document) -> None:
        self.events.append("deleting")

    async def deleted(self, instance: Document) -> None:
        self.events.append("deleted")

    async def force_deleting(self, instance: Document) -> None:
        self.events.append("force_deleting")

    async def force_deleted(self, instance: Document) -> None:
        self.events.append("force_deleted")

    async def restoring(self, instance: Document) -> None:
        self.events.append("restoring")

    async def restored(self, instance: Document) -> None:
        self.events.append("restored")


async def test_soft_delete_fires_deleting_and_deleted_only() -> None:
    recorder = _Recorder()
    Document.observe(recorder)

    target = await Document.query.where(Document.title == "alpha").first()
    assert target is not None
    async with transaction():
        await Document.query.delete(target)

    assert recorder.events == ["deleting", "deleted"]


async def test_force_delete_fires_full_chain() -> None:
    recorder = _Recorder()
    Document.observe(recorder)

    target = await Document.query.where(Document.title == "alpha").first()
    assert target is not None
    async with transaction():
        await Document.query.force_delete(target)

    assert recorder.events == [
        "deleting",
        "force_deleting",
        "force_deleted",
        "deleted",
    ]


async def test_restore_fires_restoring_and_restored() -> None:
    recorder = _Recorder()
    Document.observe(recorder)

    target = await Document.query.where(Document.title == "alpha").first()
    assert target is not None

    async with transaction():
        await Document.query.delete(target)

    recorder.events.clear()
    async with transaction():
        await Document.query.restore(target)

    assert recorder.events == ["restoring", "restored"]
