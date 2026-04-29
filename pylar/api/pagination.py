"""``Page[T]`` — pagination envelope shaped for JSON APIs (ADR-0007).

Wraps :class:`pylar.database.Paginator` in a pydantic model so the
OpenAPI generator can describe the envelope automatically:

```json
{
  "data":  [...],
  "meta":  {"page": 2, "per_page": 20, "total": 157, "total_pages": 8},
  "links": {"self": "...", "next": "...", "prev": "..."}
}
```

Controllers return ``Page[PostResource]`` and the routing compiler
auto-serialises it through the pydantic machinery.
"""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict

from pylar.database.paginator import Paginator


class PageMeta(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    page: int
    per_page: int
    total: int
    total_pages: int


class PageLinks(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    self_: str | None = None
    next: str | None = None
    prev: str | None = None


class Page[T: BaseModel](BaseModel):
    """Typed pagination envelope. Instantiate via :meth:`from_paginator`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    data: list[T]
    meta: PageMeta
    links: PageLinks

    @classmethod
    def from_paginator(
        cls,
        paginator: Paginator[object],
        resources: Iterable[T],
        *,
        base_url: str | None = None,
    ) -> Page[T]:
        """Build a ``Page`` from a :class:`Paginator` and already-serialised rows.

        *resources* is the list of pydantic instances corresponding to
        ``paginator.items`` — typically produced by a dict comprehension
        or ``[Resource.model_validate(row, from_attributes=True) for row in paginator.items]``.

        *base_url* defaults to :attr:`Paginator.path`; set it explicitly
        when the request was served under a reverse-proxied prefix that
        differs from the canonical path.
        """
        path = base_url if base_url is not None else paginator.path
        return cls(
            data=list(resources),
            meta=PageMeta(
                page=paginator.current_page,
                per_page=paginator.per_page,
                total=paginator.total,
                total_pages=paginator.last_page,
            ),
            links=PageLinks(
                self_=paginator.url_for_page(paginator.current_page) if path else None,
                next=(
                    paginator.url_for_page(paginator.current_page + 1)
                    if paginator.has_more_pages and path
                    else None
                ),
                prev=(
                    paginator.url_for_page(paginator.current_page - 1)
                    if paginator.current_page > 1 and path
                    else None
                ),
            ),
        )
