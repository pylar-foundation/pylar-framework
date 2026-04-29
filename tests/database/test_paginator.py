"""Tests for QuerySet.paginate and the Paginator value object."""

from __future__ import annotations

import pytest

from pylar.database import Paginator
from tests.database.conftest import User

pytestmark = pytest.mark.usefixtures("session")


# ----------------------------------------------------- pure Paginator API


def _paginator(items: list[str], total: int, per_page: int, page: int) -> Paginator[str]:
    return Paginator(
        items=items,
        total=total,
        per_page=per_page,
        current_page=page,
        path="/posts",
        query_params={"sort": "new"},
    )


def test_last_page_when_empty() -> None:
    p = _paginator([], 0, 10, 1)
    assert p.last_page == 1
    assert p.is_empty
    assert not p.has_more_pages


def test_last_page_division_round_up() -> None:
    p = _paginator(["a"] * 10, 47, 10, 1)
    assert p.last_page == 5


def test_first_and_last_item_indices() -> None:
    p = _paginator(["x"] * 5, 47, 10, 3)
    assert p.first_item == 21
    assert p.last_item == 25


def test_has_more_pages_and_on_first_page() -> None:
    p = _paginator(["x"], 47, 10, 1)
    assert p.on_first_page
    assert p.has_more_pages

    p = _paginator(["x"], 47, 10, 5)
    assert not p.has_more_pages
    assert not p.on_first_page


def test_url_for_page_preserves_other_query_params() -> None:
    p = _paginator(["x"], 47, 10, 1)
    assert p.url_for_page(2) == "/posts?sort=new&page=2"


def test_previous_and_next_urls() -> None:
    p = _paginator(["x"], 47, 10, 3)
    assert p.previous_page_url == "/posts?sort=new&page=2"
    assert p.next_page_url == "/posts?sort=new&page=4"

    p = _paginator(["x"], 47, 10, 1)
    assert p.previous_page_url is None

    p = _paginator(["x"], 47, 10, 5)
    assert p.next_page_url is None


def test_page_range_collapses_with_ellipses() -> None:
    p = _paginator(["x"], 990, 10, 50)  # 99 pages, current 50
    pages = p.page_range(window=2)
    assert pages[0] == 1
    assert pages[1] is None
    assert 50 in pages
    assert pages[-1] == 99


def test_page_range_short_result_no_ellipses() -> None:
    p = _paginator(["x"], 30, 10, 2)  # 3 pages
    assert p.page_range() == [1, 2, 3]


def test_to_dict_renders_laravel_envelope() -> None:
    p = _paginator(["a", "b"], 50, 10, 3)
    payload = p.to_dict()
    assert payload["meta"]["current_page"] == 3
    assert payload["meta"]["last_page"] == 5
    assert payload["meta"]["from"] == 21
    assert payload["meta"]["to"] == 22
    assert payload["links"]["next"] == "/posts?sort=new&page=4"
    assert payload["links"]["prev"] == "/posts?sort=new&page=2"


# ------------------------------------------------------ end-to-end SQL


async def test_paginate_returns_first_page_by_default() -> None:
    p = await User.query.order_by(User.name.asc()).paginate(per_page=2)
    assert p.total == 3
    assert p.last_page == 2
    assert p.current_page == 1
    assert [u.name for u in p.items] == ["Alice", "Bob"]


async def test_paginate_second_page() -> None:
    p = await User.query.order_by(User.name.asc()).paginate(per_page=2, page=2)
    assert p.current_page == 2
    assert [u.name for u in p.items] == ["Charlie"]


async def test_paginate_clamps_page_above_last() -> None:
    p = await User.query.order_by(User.name.asc()).paginate(per_page=2, page=99)
    assert p.current_page == 2
    assert [u.name for u in p.items] == ["Charlie"]


async def test_paginate_with_filters() -> None:
    p = (
        await User.query
        .where(User.active.is_(True))
        .order_by(User.name.asc())
        .paginate(per_page=10)
    )
    assert p.total == 2
    assert {u.name for u in p.items} == {"Alice", "Bob"}


async def test_paginate_empty_result() -> None:
    p = await User.query.where(User.email == "ghost@example.com").paginate()
    assert p.is_empty
    assert p.total == 0
    assert p.current_page == 1
    assert p.last_page == 1
