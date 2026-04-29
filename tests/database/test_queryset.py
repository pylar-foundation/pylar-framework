"""Tests for the chainable :class:`QuerySet` and :class:`Manager`."""

from __future__ import annotations

import pytest

from pylar.database import RecordNotFoundError, transaction
from tests.database.conftest import ConnectionManager, User

pytestmark = pytest.mark.usefixtures("session")


async def test_all_returns_every_row() -> None:
    users = await User.query.all()
    assert {u.email for u in users} == {
        "alice@example.com",
        "bob@example.com",
        "charlie@example.com",
    }


async def test_where_filters_rows() -> None:
    actives = await User.query.where(User.active.is_(True)).all()
    assert {u.name for u in actives} == {"Alice", "Bob"}


async def test_where_chains_are_immutable() -> None:
    base = User.query.where(User.active.is_(True))
    narrowed = base.where(User.name == "Alice")

    assert len(await base.all()) == 2
    assert len(await narrowed.all()) == 1


async def test_order_by_and_limit() -> None:
    page = await User.query.order_by(User.name.asc()).limit(2).all()
    assert [u.name for u in page] == ["Alice", "Bob"]


async def test_offset() -> None:
    page = await User.query.order_by(User.name.asc()).offset(1).limit(1).all()
    assert [u.name for u in page] == ["Bob"]


async def test_first_returns_one_or_none() -> None:
    found = await User.query.where(User.email == "alice@example.com").first()
    assert found is not None
    assert found.name == "Alice"

    missing = await User.query.where(User.email == "nope@example.com").first()
    assert missing is None


async def test_get_by_primary_key() -> None:
    one = await User.query.first()
    assert one is not None
    fetched = await User.query.get(one.id)
    assert fetched.id == one.id


async def test_get_missing_raises_record_not_found() -> None:
    with pytest.raises(RecordNotFoundError):
        await User.query.get(99999)


async def test_count_respects_filters() -> None:
    assert await User.query.count() == 3
    assert await User.query.where(User.active.is_(True)).count() == 2


async def test_exists() -> None:
    assert await User.query.where(User.email == "alice@example.com").exists()
    assert not await User.query.where(User.email == "ghost").exists()


async def test_delete_with_where_returns_row_count() -> None:
    async with transaction():
        affected = await User.query.where(User.active.is_(False)).delete()
    assert affected == 1
    assert await User.query.count() == 2


async def test_save_persists_new_row(manager: ConnectionManager) -> None:
    # Use a fresh ambient session — the conftest one is already active.
    async with transaction():
        new_user = User(email="zoe@example.com", name="Zoe")
        await User.query.save(new_user)  # type: ignore[attr-defined]
        # auto-id assigned after flush
        assert new_user.id is not None

    fetched = await User.query.where(User.email == "zoe@example.com").first()
    assert fetched is not None
    assert fetched.name == "Zoe"


async def test_manager_delete_removes_instance() -> None:
    target = await User.query.where(User.email == "bob@example.com").first()
    assert target is not None
    async with transaction():
        await User.query.delete(target)  # type: ignore[arg-type]

    assert await User.query.where(User.email == "bob@example.com").first() is None
