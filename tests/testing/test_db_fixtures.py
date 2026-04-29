"""Tests for the new auto-DB fixtures and Factory helpers."""

from __future__ import annotations

from typing import ClassVar

import pytest
from sqlalchemy.orm import Mapped, mapped_column

from pylar.database import ConnectionManager, Model, use_session
from pylar.testing import Factory, Sequence, bootstrap_schema, in_memory_manager


class FixtureUser(Model):
    __tablename__ = "test_fixture_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(unique=True)
    name: Mapped[str]
    role: Mapped[str] = mapped_column(default="member")


# ----------------------------------------------------------- bootstrap_schema


async def test_in_memory_manager_creates_tables() -> None:
    async with in_memory_manager() as manager:
        async with use_session(manager) as sess:
            sess.add(FixtureUser(email="a@b", name="A"))
            await sess.commit()
        async with use_session(manager) as sess:
            users = await FixtureUser.query.all(session=sess)
            assert len(users) == 1


async def test_bootstrap_schema_is_idempotent() -> None:
    async with in_memory_manager() as manager:
        await bootstrap_schema(manager)
        await bootstrap_schema(manager)  # second call must not crash


# ----------------------------------------------------------- pylar_db_manager


async def test_pylar_db_manager_fixture(
    pylar_db_manager: ConnectionManager,
) -> None:
    async with use_session(pylar_db_manager) as sess:
        sess.add(FixtureUser(email="x@y", name="X"))
        await sess.commit()
        rows = await FixtureUser.query.all(session=sess)
        assert len(rows) == 1


# --------------------------------------------------------------- Factory dx


email_seq = Sequence(lambda n: f"user-{n}@example.com")


class FixtureUserFactory(Factory[FixtureUser]):
    traits: ClassVar[dict[str, dict[str, object]]] = {
        "admin": {"role": "admin"},
        "guest": {"role": "guest"},
    }

    @classmethod
    def model_class(cls) -> type[FixtureUser]:
        return FixtureUser

    def definition(self) -> dict[str, object]:
        return {"email": email_seq.next(), "name": "Sample"}


async def test_factory_make_uses_sequence() -> None:
    a = FixtureUserFactory().make()
    b = FixtureUserFactory().make()
    assert a.email != b.email


async def test_factory_with_trait_applies_overrides() -> None:
    user = FixtureUserFactory().with_trait("admin").make()
    assert user.role == "admin"


async def test_factory_with_trait_unknown_raises() -> None:
    with pytest.raises(KeyError, match="ghost"):
        FixtureUserFactory().with_trait("ghost")


async def test_factory_make_many() -> None:
    users = FixtureUserFactory().make_many(3)
    assert len(users) == 3
    assert len({u.email for u in users}) == 3


async def test_factory_create_many_persists(
    pylar_db_manager: ConnectionManager, pylar_db_session: None
) -> None:
    await FixtureUserFactory().create_many(3)
    rows = await FixtureUser.query.all()
    assert len(rows) == 3
