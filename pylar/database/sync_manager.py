"""Synchronous wrappers around :class:`Manager` and :class:`QuerySet`.

Every async method gets a sync twin that awaits the underlying
coroutine through the event loop. Useful in scripts, seeders, data
migrations, and the tinker REPL where ``await`` is cumbersome.

Access via ``Model.query.sync``::

    posts = Post.query.sync.all()
    post = Post.query.sync.get(1)
    post.title = "new"
    Post.query.sync.save(post)

    # Chains work too:
    published = Post.query.where(Post.published.is_(True)).sync.all()

Under the hood the helper reuses the running event loop when one
exists (via ``nest_asyncio``) and falls back to ``asyncio.run()``
otherwise. Inside a request handler prefer the native async API —
this wrapper is meant for sync contexts.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable
from typing import TYPE_CHECKING

from sqlalchemy import ColumnElement
from sqlalchemy.ext.asyncio import AsyncSession

from pylar.database.expressions import Q
from pylar.database.paginator import Paginator
from pylar.database.queryset import QuerySet

if TYPE_CHECKING:
    from pylar.database.manager import Manager

def run_sync[T](coro: Awaitable[T]) -> T:
    """Run *coro* from synchronous code.

    Handles both cases:

    * No running loop — calls :func:`asyncio.run` directly.
    * Running loop (e.g. inside IPython autoawait, Jupyter, or the
      tinker REPL) — patches the loop with ``nest_asyncio`` and
      awaits through it.
    """
    if not inspect.isawaitable(coro):
        return coro

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)  # type: ignore[arg-type]

    # nest_asyncio is a core dependency so it is always available.
    import nest_asyncio

    nest_asyncio.apply(loop)
    return loop.run_until_complete(coro)


class SyncQuerySet[ModelT]:
    """Synchronous façade over :class:`QuerySet`.

    Chain operators return new :class:`SyncQuerySet` instances; terminal
    operations (``all``, ``first``, ``count``, ...) block and return the
    awaited value.
    """

    __slots__ = ("_qs",)

    def __init__(self, qs: QuerySet[ModelT]) -> None:
        self._qs = qs

    # ---- chain operators (return new SyncQuerySet) ----

    def where(self, *conditions: ColumnElement[bool] | Q) -> SyncQuerySet[ModelT]:
        return SyncQuerySet(self._qs.where(*conditions))

    def order_by(self, *expressions: ColumnElement[object]) -> SyncQuerySet[ModelT]:
        return SyncQuerySet(self._qs.order_by(*expressions))

    def limit(self, n: int) -> SyncQuerySet[ModelT]:
        return SyncQuerySet(self._qs.limit(n))

    def offset(self, n: int) -> SyncQuerySet[ModelT]:
        return SyncQuerySet(self._qs.offset(n))

    def with_(self, *relations: str) -> SyncQuerySet[ModelT]:
        return SyncQuerySet(self._qs.with_(*relations))

    def with_trashed(self) -> SyncQuerySet[ModelT]:
        return SyncQuerySet(self._qs.with_trashed())

    def only_trashed(self) -> SyncQuerySet[ModelT]:
        return SyncQuerySet(self._qs.only_trashed())

    # ---- terminal operations (block and return) ----

    def all(self, *, session: AsyncSession | None = None) -> list[ModelT]:
        return run_sync(self._qs.all(session=session))

    def first(self, *, session: AsyncSession | None = None) -> ModelT | None:
        return run_sync(self._qs.first(session=session))

    def get(
        self, primary_key: object, *, session: AsyncSession | None = None
    ) -> ModelT:
        return run_sync(self._qs.get(primary_key, session=session))

    def count(self, *, session: AsyncSession | None = None) -> int:
        return run_sync(self._qs.count(session=session))

    def exists(self, *, session: AsyncSession | None = None) -> bool:
        return run_sync(self._qs.exists(session=session))

    def paginate(
        self,
        *,
        page: int = 1,
        per_page: int = 15,
        path: str = "",
        query_params: dict[str, str] | None = None,
        session: AsyncSession | None = None,
    ) -> Paginator[ModelT]:
        return run_sync(
            self._qs.paginate(
                page=page,
                per_page=per_page,
                path=path,
                query_params=query_params,
                session=session,
            )
        )

    def delete(self, *, session: AsyncSession | None = None) -> int:
        return run_sync(self._qs.delete(session=session))


class SyncManager[ModelT]:
    """Synchronous façade over :class:`Manager`.

    Exposed as ``Manager.sync`` — typical use::

        Post.query.sync.all()
        Post.query.sync.where(Post.published.is_(True)).first()
        Post.query.sync.save(post)
    """

    __slots__ = ("_manager",)

    def __init__(self, manager: Manager[ModelT]) -> None:
        self._manager = manager

    # ---- chain operators ----

    def where(self, *conditions: ColumnElement[bool] | Q) -> SyncQuerySet[ModelT]:
        return SyncQuerySet(self._manager.where(*conditions))

    def order_by(self, *expressions: ColumnElement[object]) -> SyncQuerySet[ModelT]:
        return SyncQuerySet(self._manager.order_by(*expressions))

    def limit(self, n: int) -> SyncQuerySet[ModelT]:
        return SyncQuerySet(self._manager.limit(n))

    def offset(self, n: int) -> SyncQuerySet[ModelT]:
        return SyncQuerySet(self._manager.offset(n))

    def with_(self, *relations: str) -> SyncQuerySet[ModelT]:
        return SyncQuerySet(self._manager.with_(*relations))

    def with_trashed(self) -> SyncQuerySet[ModelT]:
        return SyncQuerySet(self._manager.with_trashed())

    def only_trashed(self) -> SyncQuerySet[ModelT]:
        return SyncQuerySet(self._manager.only_trashed())

    # ---- terminal reads ----

    def all(self, *, session: AsyncSession | None = None) -> list[ModelT]:
        return run_sync(self._manager.all(session=session))

    def first(self, *, session: AsyncSession | None = None) -> ModelT | None:
        return run_sync(self._manager.first(session=session))

    def get(
        self, primary_key: object, *, session: AsyncSession | None = None
    ) -> ModelT:
        return run_sync(self._manager.get(primary_key, session=session))

    def count(self, *, session: AsyncSession | None = None) -> int:
        return run_sync(self._manager.count(session=session))

    def paginate(
        self,
        *,
        page: int = 1,
        per_page: int = 15,
        path: str = "",
        query_params: dict[str, str] | None = None,
        session: AsyncSession | None = None,
    ) -> Paginator[ModelT]:
        return run_sync(
            self._manager.paginate(
                page=page,
                per_page=per_page,
                path=path,
                query_params=query_params,
                session=session,
            )
        )

    # ---- single-row writes ----

    def save(
        self, instance: ModelT, *, session: AsyncSession | None = None
    ) -> ModelT:
        return run_sync(self._manager.save(instance, session=session))

    def delete(
        self, instance: ModelT, *, session: AsyncSession | None = None
    ) -> None:
        return run_sync(self._manager.delete(instance, session=session))

    def force_delete(
        self, instance: ModelT, *, session: AsyncSession | None = None
    ) -> None:
        return run_sync(self._manager.force_delete(instance, session=session))

    def restore(
        self, instance: ModelT, *, session: AsyncSession | None = None
    ) -> ModelT:
        return run_sync(self._manager.restore(instance, session=session))
