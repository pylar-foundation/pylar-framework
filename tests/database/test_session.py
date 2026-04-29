"""Tests for :mod:`pylar.database.session` and the transaction helper."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from pylar.database import (
    ConnectionManager,
    NoActiveSessionError,
    current_session,
    transaction,
    use_session,
)
from tests.database.conftest import User


def test_current_session_outside_scope_raises() -> None:
    with pytest.raises(NoActiveSessionError, match="No active database session"):
        current_session()


async def test_use_session_installs_and_clears_contextvar(
    manager: ConnectionManager,
) -> None:
    async with use_session(manager) as session:
        assert current_session() is session
    with pytest.raises(NoActiveSessionError):
        current_session()


async def test_transaction_commits_on_success(manager: ConnectionManager) -> None:
    async with use_session(manager):
        async with transaction():
            sess = current_session()
            sess.add(User(email="dave@example.com", name="Dave"))

    async with use_session(manager) as sess:
        result = await sess.execute(select(User).where(User.email == "dave@example.com"))
        assert result.scalar_one().name == "Dave"


async def test_transaction_rolls_back_on_exception(manager: ConnectionManager) -> None:
    with pytest.raises(RuntimeError, match="boom"):
        async with use_session(manager):
            async with transaction():
                sess = current_session()
                sess.add(User(email="erin@example.com", name="Erin"))
                raise RuntimeError("boom")

    async with use_session(manager) as sess:
        result = await sess.execute(select(User).where(User.email == "erin@example.com"))
        assert result.scalar_one_or_none() is None
