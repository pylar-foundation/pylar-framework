"""Tests for the F / Q expression helpers."""

from __future__ import annotations

import pytest

from pylar.database import F, Q
from tests.database.conftest import User

pytestmark = pytest.mark.usefixtures("session")


# ----------------------------------------------------------------- Q kwargs


async def test_q_kwargs_equality() -> None:
    rows = await User.query.where(Q(active=True)).all()
    assert {u.name for u in rows} == {"Alice", "Bob"}


async def test_q_kwargs_multiple_clauses_are_anded() -> None:
    rows = await User.query.where(Q(active=True, name="Alice")).all()
    assert [u.name for u in rows] == ["Alice"]


async def test_q_kwargs_with_lookup_suffix() -> None:
    rows = await User.query.where(Q(name__icontains="li")).all()
    assert {u.name for u in rows} == {"Alice", "Charlie"}


async def test_q_kwargs_in_lookup() -> None:
    rows = await User.query.where(Q(name__in=("Alice", "Bob"))).all()
    assert {u.name for u in rows} == {"Alice", "Bob"}


async def test_q_kwargs_isnull_false() -> None:
    rows = await User.query.where(Q(email__isnull=False)).all()
    assert len(rows) == 3


async def test_q_kwargs_unknown_column_raises() -> None:
    with pytest.raises(AttributeError, match="ghost"):
        await User.query.where(Q(ghost=True)).all()


async def test_q_kwargs_unknown_lookup_raises() -> None:
    with pytest.raises(ValueError, match="Unknown lookup"):
        await User.query.where(Q(name__regex="^A")).all()


# --------------------------------------------------------- combinators / not


async def test_q_or_combines_predicates() -> None:
    rows = await User.query.where(
        Q(name="Alice") | Q(name="Charlie")
    ).all()
    assert {u.name for u in rows} == {"Alice", "Charlie"}


async def test_q_and_narrows_predicates() -> None:
    rows = await User.query.where(
        Q(active=True) & Q(name__startswith="A")
    ).all()
    assert [u.name for u in rows] == ["Alice"]


async def test_q_invert_negates_predicate() -> None:
    rows = await User.query.where(~Q(active=True)).all()
    assert [u.name for u in rows] == ["Charlie"]


async def test_q_complex_tree() -> None:
    rows = await User.query.where(
        (Q(name="Alice") | Q(name="Bob")) & Q(active=True)
    ).all()
    assert {u.name for u in rows} == {"Alice", "Bob"}


# --------------------------------------------------------------- F references


async def test_f_comparison_against_literal() -> None:
    rows = await User.query.where(F("name") == "Alice").all()
    assert [u.name for u in rows] == ["Alice"]


async def test_f_combines_with_q() -> None:
    rows = await User.query.where(
        Q(active=True) & (F("name") == "Bob")
    ).all()
    assert [u.name for u in rows] == ["Bob"]


async def test_f_unknown_column_raises_at_compile_time() -> None:
    with pytest.raises(AttributeError, match="ghost"):
        await User.query.where(F("ghost") == 1).all()


# ---------------------------------------------------------- mix with raw SA


async def test_q_can_coexist_with_raw_sqlalchemy_predicates() -> None:
    rows = await User.query.where(
        Q(active=True), User.name != "Alice"
    ).all()
    assert [u.name for u in rows] == ["Bob"]
