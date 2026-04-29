"""Length-aware paginator — pylar's typed answer to Laravel's ``Paginator``.

A :class:`Paginator` is the typed result of :meth:`QuerySet.paginate`.
It carries the page slice that the database returned plus enough
metadata for templates and JSON responses to render navigation
controls without having to query the database again:

* :attr:`items` — the actual model instances on the current page.
* :attr:`total` — the row count for the *unpaginated* query, fetched
  in the same call via a separate ``SELECT COUNT(*)``.
* :attr:`per_page` and :attr:`current_page` — what the caller asked
  for, normalised so ``current_page`` is at least 1 and never above
  ``last_page``.
* :attr:`last_page` — derived from ``total`` and ``per_page``;
  ``1`` when the result set is empty so templates do not have to
  special-case the empty case.

The class is intentionally framework-agnostic on the rendering side:
it exposes the data and a few helpers (``has_more_pages``,
``page_range``, ``url_for_page``) and leaves layout to the
application's templates. The blog example ships a small Jinja partial
that renders these into Laravel-style page links.

Why a dedicated class instead of a tuple?
-----------------------------------------

Returning ``(items, total)`` works for one or two call sites but
forces every template to recompute ``last_page = ceil(total /
per_page)`` itself, which is exactly the kind of arithmetic the
framework should own. The :class:`Paginator` keeps that logic in one
place and gives templates a stable surface to bind against.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import dataclass
from urllib.parse import urlencode


@dataclass(frozen=True, slots=True)
class Paginator[ModelT]:
    """A page slice plus the metadata needed to render navigation controls."""

    items: list[ModelT]
    total: int
    per_page: int
    current_page: int
    path: str = ""
    query_params: dict[str, str] | None = None

    @property
    def last_page(self) -> int:
        if self.total == 0 or self.per_page == 0:
            return 1
        return max(1, math.ceil(self.total / self.per_page))

    @property
    def first_item(self) -> int:
        """1-indexed position of the first row on the current page (0 if empty)."""
        if not self.items:
            return 0
        return (self.current_page - 1) * self.per_page + 1

    @property
    def last_item(self) -> int:
        """1-indexed position of the last row on the current page (0 if empty)."""
        if not self.items:
            return 0
        return self.first_item + len(self.items) - 1

    @property
    def has_more_pages(self) -> bool:
        return self.current_page < self.last_page

    @property
    def on_first_page(self) -> bool:
        return self.current_page <= 1

    @property
    def is_empty(self) -> bool:
        return not self.items

    def __iter__(self) -> Iterator[ModelT]:
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    def page_range(self, *, window: int = 2) -> list[int | None]:
        """Return a list of page numbers around :attr:`current_page`.

        ``None`` entries are placeholders for ``…`` ellipsis blocks so
        long page lists collapse cleanly. ``window=2`` produces
        ``[1, None, 4, 5, 6, None, 99]`` for a current page of 5 in
        a 99-page result.
        """
        last = self.last_page
        if last <= 1:
            return [1]
        pages: list[int | None] = []
        start = max(1, self.current_page - window)
        end = min(last, self.current_page + window)
        if start > 1:
            pages.append(1)
            if start > 2:
                pages.append(None)
        for p in range(start, end + 1):
            pages.append(p)
        if end < last:
            if end < last - 1:
                pages.append(None)
            pages.append(last)
        return pages

    def url_for_page(self, page: int) -> str:
        """Build the URL for *page* using :attr:`path` + :attr:`query_params`.

        The current ``page`` query string is overwritten with the
        target page; everything else is preserved so filters and
        search terms survive pagination clicks.
        """
        params = dict(self.query_params or {})
        params["page"] = str(page)
        query = urlencode(params)
        if not self.path:
            return f"?{query}"
        if "?" in self.path:
            return f"{self.path}&{query}"
        return f"{self.path}?{query}"

    @property
    def previous_page_url(self) -> str | None:
        if self.on_first_page:
            return None
        return self.url_for_page(self.current_page - 1)

    @property
    def next_page_url(self) -> str | None:
        if not self.has_more_pages:
            return None
        return self.url_for_page(self.current_page + 1)

    def to_dict(self) -> dict[str, object]:
        """Render the paginator into a Laravel-style JSON envelope."""
        return {
            "data": list(self.items),
            "meta": {
                "current_page": self.current_page,
                "last_page": self.last_page,
                "per_page": self.per_page,
                "total": self.total,
                "from": self.first_item,
                "to": self.last_item,
            },
            "links": {
                "first": self.url_for_page(1) if self.path else None,
                "last": self.url_for_page(self.last_page) if self.path else None,
                "prev": self.previous_page_url,
                "next": self.next_page_url,
            },
        }


@dataclass(frozen=True, slots=True)
class SimplePaginator[ModelT]:
    """A lightweight paginator that skips the COUNT query.

    Matches Laravel's ``simplePaginate()`` — only knows whether there
    is a next page (fetches ``per_page + 1`` rows and checks), but
    never hits the database with ``SELECT COUNT(*)``. Ideal for large
    tables where the count is expensive and the UI only needs
    Previous / Next links without a total.
    """

    items: list[ModelT]
    per_page: int
    current_page: int
    has_more_pages: bool
    path: str = ""
    query_params: dict[str, str] | None = None

    @property
    def on_first_page(self) -> bool:
        return self.current_page <= 1

    @property
    def is_empty(self) -> bool:
        return not self.items

    def __iter__(self) -> Iterator[ModelT]:
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    def url_for_page(self, page: int) -> str:
        params = dict(self.query_params or {})
        params["page"] = str(page)
        query = urlencode(params)
        if not self.path:
            return f"?{query}"
        return f"{self.path}?{query}"

    @property
    def previous_page_url(self) -> str | None:
        if self.on_first_page:
            return None
        return self.url_for_page(self.current_page - 1)

    @property
    def next_page_url(self) -> str | None:
        if not self.has_more_pages:
            return None
        return self.url_for_page(self.current_page + 1)

    def to_dict(self) -> dict[str, object]:
        return {
            "data": list(self.items),
            "meta": {
                "current_page": self.current_page,
                "per_page": self.per_page,
            },
            "links": {
                "prev": self.previous_page_url,
                "next": self.next_page_url,
            },
        }
