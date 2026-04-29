"""Chainable, lazy, typed wrapper around :func:`sqlalchemy.select`.

A :class:`QuerySet` is immutable: every chain method (``where``, ``order_by``,
``limit``, ``offset``, ``with_trashed``, ``only_trashed``) returns a new
:class:`QuerySet` with the modified state, leaving the original untouched.
This matches Django's QuerySet ergonomics while staying entirely on top of
SQLAlchemy 2.0's typed Core API.

Terminal methods (``all``, ``first``, ``get``, ``count``, ``exists``,
``delete``, ``force_delete``) are async and use the ambient session
installed by :func:`pylar.database.use_session`.

Soft-delete awareness
---------------------

When the model class inherits :class:`pylar.database.SoftDeletes` the
QuerySet automatically excludes rows whose ``deleted_at`` column is not
``NULL``. The behaviour is implemented at statement-build time, not by
appending to the ``where`` list, so callers can flip it on a single chain
without having to remember to drop a previously-added condition::

    posts = await Post.query.where(Post.published).all()
    # → WHERE published = TRUE AND deleted_at IS NULL

    archived = await Post.query.where(Post.published).only_trashed().all()
    # → WHERE published = TRUE AND deleted_at IS NOT NULL

For models that do not mix in :class:`SoftDeletes` the trashed-mode flag
is silently ignored — no extra WHERE clause is emitted.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Literal, cast

from sqlalchemy import ColumnElement, Delete, Select, Update, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.strategy_options import _AbstractLoad

from pylar.database.exceptions import RecordNotFoundError
from pylar.database.expressions import Q
from pylar.database.paginator import Paginator, SimplePaginator
from pylar.database.session import current_session

#: How a QuerySet treats soft-deleted rows. ``exclude`` is the default and
#: matches Laravel's behaviour: trashed rows are invisible until the caller
#: opts in via :meth:`with_trashed` or :meth:`only_trashed`.
TrashedMode = Literal["exclude", "include", "only"]


@dataclass(frozen=True, slots=True)
class _State:
    """Internal accumulator for the in-progress query."""

    conditions: tuple[ColumnElement[bool], ...] = ()
    order: tuple[ColumnElement[object], ...] = ()
    limit_value: int | None = None
    offset_value: int | None = None
    trashed_mode: TrashedMode = "exclude"
    eager: tuple[str, ...] = ()


class QuerySet[ModelT]:
    """Lazy, chainable query builder bound to a single model class."""

    def __init__(self, model: type[ModelT], state: _State | None = None) -> None:
        self._model = model
        self._state = state if state is not None else _State()

    @classmethod
    def for_model(cls, model: type[ModelT]) -> QuerySet[ModelT]:
        return cls(model=model)

    @property
    def sync(self) -> Any:
        """Synchronous façade — block instead of returning coroutines.

        Every terminal method (``all``, ``first``, ``count``, ...)
        returns the awaited value directly. Chain operators return a
        sync queryset so the entire chain stays synchronous::

            Post.query.where(Post.published.is_(True)).sync.all()
        """
        from pylar.database.sync_manager import SyncQuerySet

        return SyncQuerySet(self)

    # ----------------------------------------------------------- chain operators

    def where(
        self, *conditions: ColumnElement[bool] | Q
    ) -> QuerySet[ModelT]:
        """Append predicates to the WHERE clause.

        Accepts both raw SQLAlchemy ``ColumnElement[bool]`` predicates
        and :class:`pylar.database.Q` expressions; ``Q`` instances are
        compiled against the bound model right away so the rest of the
        QuerySet pipeline only ever sees plain SA expressions.
        """
        compiled: tuple[ColumnElement[bool], ...] = tuple(
            c.compile(self._model) if isinstance(c, Q) else c for c in conditions
        )
        return QuerySet(
            self._model,
            replace(self._state, conditions=(*self._state.conditions, *compiled)),
        )

    def order_by(self, *expressions: ColumnElement[object]) -> QuerySet[ModelT]:
        return QuerySet(
            self._model,
            replace(self._state, order=(*self._state.order, *expressions)),
        )

    def limit(self, n: int) -> QuerySet[ModelT]:
        return QuerySet(self._model, replace(self._state, limit_value=n))

    def offset(self, n: int) -> QuerySet[ModelT]:
        return QuerySet(self._model, replace(self._state, offset_value=n))

    def with_(self, *relations: str) -> QuerySet[ModelT]:
        """Eager-load the named relationships using ``selectinload``.

        Each argument is the dotted path of a relationship attribute on
        the bound model — single-level (``"author"``) or nested
        (``"author.profile"``). The QuerySet emits one extra SELECT per
        relationship at execution time, so the returned instances arrive
        with their related rows already attached and the caller does not
        trip the SQLAlchemy lazy-loading guard inside an async context::

            posts = await Post.query.with_("author", "tags").all()
            for post in posts:
                # No additional query — author and tags are already loaded.
                print(post.author.name, [t.name for t in post.tags])

        Repeated calls accumulate, so chains can append additional
        relationships incrementally:

            qs = Post.query.with_("author")
            qs = qs.with_("comments.user")
        """
        for path in relations:
            if not path:
                raise ValueError("with_() does not accept empty relationship paths")
        return QuerySet(
            self._model,
            replace(self._state, eager=(*self._state.eager, *relations)),
        )

    # ------------------------------------------------------- soft-delete chain

    def with_trashed(self) -> QuerySet[ModelT]:
        """Include soft-deleted rows in the result set."""
        return QuerySet(self._model, replace(self._state, trashed_mode="include"))

    def only_trashed(self) -> QuerySet[ModelT]:
        """Return only the soft-deleted rows."""
        return QuerySet(self._model, replace(self._state, trashed_mode="only"))

    def without_trashed(self) -> QuerySet[ModelT]:
        """Restore the default exclusion of soft-deleted rows."""
        return QuerySet(self._model, replace(self._state, trashed_mode="exclude"))

    # --------------------------------------------------------- terminal: reads

    async def all(self, *, session: AsyncSession | None = None) -> list[ModelT]:
        sess = self._resolve_session(session)
        result = await sess.execute(self._build_select())
        return list(result.scalars().all())

    async def first(self, *, session: AsyncSession | None = None) -> ModelT | None:
        sess = self._resolve_session(session)
        statement = self._build_select().limit(1)
        result = await sess.execute(statement)
        return result.scalars().first()

    async def get(self, primary_key: object, *, session: AsyncSession | None = None) -> ModelT:
        sess = self._resolve_session(session)
        instance = await sess.get(self._model, primary_key)
        if instance is None:
            raise RecordNotFoundError(self._model, primary_key)
        return instance

    async def count(self, *, session: AsyncSession | None = None) -> int:
        sess = self._resolve_session(session)
        statement = select(func.count()).select_from(self._model)
        for condition in self._all_conditions():
            statement = statement.where(condition)
        result = await sess.execute(statement)
        return int(result.scalar_one())

    async def exists(self, *, session: AsyncSession | None = None) -> bool:
        return await self.count(session=session) > 0

    async def first_or_create(
        self,
        defaults: dict[str, object] | None = None,
        *,
        session: AsyncSession | None = None,
    ) -> tuple[ModelT, bool]:
        """Return the first matching row, or create one if none exists.

        The ``where`` conditions on the QuerySet define the lookup
        criteria. If no row matches, a new instance is created with
        the lookup values + *defaults* merged, added to the session,
        and flushed.

        Returns ``(instance, created)`` — the bool is ``True`` when a
        new row was inserted. Matches Laravel's ``firstOrCreate``.
        """
        sess = self._resolve_session(session)
        existing = await self.first(session=sess)
        if existing is not None:
            return existing, False
        attrs = dict(defaults or {})
        instance = self._model(**attrs)
        sess.add(instance)
        await sess.flush()
        return instance, True

    async def update_or_create(
        self,
        defaults: dict[str, object],
        *,
        session: AsyncSession | None = None,
    ) -> tuple[ModelT, bool]:
        """Update the first matching row, or create one if none exists.

        The ``where`` conditions define the lookup. If a row is found
        its attributes are updated from *defaults* and flushed. If no
        row is found a new instance is created with *defaults*, added,
        and flushed.

        Returns ``(instance, created)``. Matches Laravel's
        ``updateOrCreate``.
        """
        sess = self._resolve_session(session)
        existing = await self.first(session=sess)
        if existing is not None:
            for key, value in defaults.items():
                setattr(existing, key, value)
            sess.add(existing)
            await sess.flush()
            return existing, False
        attrs = dict(defaults)
        instance = self._model(**attrs)
        sess.add(instance)
        await sess.flush()
        return instance, True

    async def paginate(
        self,
        *,
        page: int = 1,
        per_page: int = 15,
        path: str = "",
        query_params: dict[str, str] | None = None,
        session: AsyncSession | None = None,
    ) -> Paginator[ModelT]:
        """Run two queries — ``COUNT(*)`` plus the page slice — and wrap them.

        Returns a :class:`pylar.database.Paginator` whose ``items`` is
        the page slice and whose metadata fields (``total``,
        ``last_page``, ``current_page``) are ready for templates and
        JSON envelopes. ``page`` is clamped to ``[1, last_page]`` so a
        caller that asks for page 999 of a 5-page result quietly gets
        page 5 instead of an empty payload — matches Laravel's
        behaviour.

        ``order_by``, ``with_``, and ``where`` clauses on the underlying
        QuerySet are honoured. ``limit`` / ``offset`` set on the
        QuerySet itself are *replaced* by the paginator's slice — the
        whole point of pagination is that the framework computes them.
        """
        per_page = max(1, per_page)
        page = max(1, page)

        sess = self._resolve_session(session)
        total = await self.count(session=sess)

        if total == 0:
            return Paginator(
                items=[],
                total=0,
                per_page=per_page,
                current_page=1,
                path=path,
                query_params=query_params,
            )

        last_page = max(1, (total + per_page - 1) // per_page)
        page = min(page, last_page)
        offset = (page - 1) * per_page

        statement = self._build_select().limit(per_page).offset(offset)
        result = await sess.execute(statement)
        items = list(result.scalars().all())

        return Paginator(
            items=items,
            total=total,
            per_page=per_page,
            current_page=page,
            path=path,
            query_params=query_params,
        )

    async def simple_paginate(
        self,
        *,
        page: int = 1,
        per_page: int = 15,
        path: str = "",
        query_params: dict[str, str] | None = None,
        session: AsyncSession | None = None,
    ) -> SimplePaginator[ModelT]:
        """Paginate without a COUNT query.

        Fetches ``per_page + 1`` rows: the extra row tells us whether
        there is a next page. No ``SELECT COUNT(*)`` is issued, so this
        is significantly faster on large tables where only Previous /
        Next navigation is needed.

        Matches Laravel's ``simplePaginate()``.
        """
        per_page = max(1, per_page)
        page = max(1, page)
        offset = (page - 1) * per_page

        sess = self._resolve_session(session)
        statement = self._build_select().limit(per_page + 1).offset(offset)
        result = await sess.execute(statement)
        rows = list(result.scalars().all())

        has_more = len(rows) > per_page
        items = rows[:per_page]

        return SimplePaginator(
            items=items,
            per_page=per_page,
            current_page=page,
            has_more_pages=has_more,
            path=path,
            query_params=query_params,
        )

    # -------------------------------------------------------- terminal: writes

    async def delete(self, *, session: AsyncSession | None = None) -> int:
        """Delete every row matched by the current ``where`` clauses.

        For models that inherit :class:`SoftDeletes` this issues an
        ``UPDATE … SET deleted_at = now()`` instead of a ``DELETE`` so the
        rows survive on disk and can be restored later. Use
        :meth:`force_delete` when you really want them gone.

        ``order_by``, ``limit`` and ``offset`` are ignored — bulk delete
        with limits is intentionally unsupported because most databases do
        not handle it portably.
        """
        from datetime import UTC, datetime

        sess = self._resolve_session(session)

        statement: Update | Delete
        if _is_soft_delete(self._model):
            statement = update(self._model).values(deleted_at=datetime.now(UTC))
        else:
            statement = delete(self._model)

        for condition in self._all_conditions():
            statement = statement.where(condition)
        result = await sess.execute(statement)
        rowcount = cast(Any, result).rowcount
        return int(rowcount or 0)

    async def force_delete(self, *, session: AsyncSession | None = None) -> int:
        """Issue an unconditional ``DELETE``, bypassing any soft-delete logic."""
        sess = self._resolve_session(session)
        statement = delete(self._model)
        for condition in self._all_conditions():
            statement = statement.where(condition)
        result = await sess.execute(statement)
        rowcount = cast(Any, result).rowcount
        return int(rowcount or 0)

    # ---------------------------------------------------------------- introspect

    def to_select(self) -> Select[tuple[ModelT]]:
        """Return the underlying SQLAlchemy :class:`Select` for advanced cases."""
        return self._build_select()

    def __repr__(self) -> str:
        return f"<QuerySet[{self._model.__name__}]>"

    # ------------------------------------------------------------------ internals

    def _build_select(self) -> Select[tuple[ModelT]]:
        statement: Select[tuple[ModelT]] = select(self._model)
        for condition in self._all_conditions():
            statement = statement.where(condition)
        if self._state.order:
            statement = statement.order_by(*self._state.order)
        if self._state.limit_value is not None:
            statement = statement.limit(self._state.limit_value)
        if self._state.offset_value is not None:
            statement = statement.offset(self._state.offset_value)
        for option in self._eager_options():
            statement = statement.options(option)
        return statement

    def _eager_options(self) -> tuple[_AbstractLoad, ...]:
        """Translate ``with_("a.b", "c")`` paths into selectinload chains."""
        options: list[_AbstractLoad] = []
        for path in self._state.eager:
            parts = path.split(".")
            cls = self._model
            head = getattr(cls, parts[0], None)
            if head is None:
                raise AttributeError(
                    f"{cls.__name__} has no relationship {parts[0]!r}"
                )
            loader = selectinload(head)
            owner = _related_model(head)
            for segment in parts[1:]:
                if owner is None:
                    raise AttributeError(
                        f"Cannot resolve nested path {path!r}: "
                        f"{parts[0]!r} has no related model"
                    )
                attr = getattr(owner, segment, None)
                if attr is None:
                    raise AttributeError(
                        f"{owner.__name__} has no relationship {segment!r}"
                    )
                loader = loader.selectinload(attr)
                owner = _related_model(attr)
            options.append(loader)
        return tuple(options)

    def _all_conditions(self) -> tuple[ColumnElement[bool], ...]:
        """Return user conditions plus the implicit soft-delete filter."""
        soft_filter = self._soft_delete_filter()
        if soft_filter is None:
            return self._state.conditions
        return (soft_filter, *self._state.conditions)

    def _soft_delete_filter(self) -> ColumnElement[bool] | None:
        if not _is_soft_delete(self._model):
            return None
        column = cast(Any, self._model).deleted_at
        if self._state.trashed_mode == "exclude":
            return cast(ColumnElement[bool], column.is_(None))
        if self._state.trashed_mode == "only":
            return cast(ColumnElement[bool], column.is_not(None))
        return None  # "include" → no filter

    @staticmethod
    def _resolve_session(session: AsyncSession | None) -> AsyncSession:
        return session if session is not None else current_session()


def _related_model(attribute: Any) -> type[Any] | None:
    """Return the model class on the far side of a relationship attribute."""
    prop = getattr(attribute, "property", None)
    if prop is None:
        return None
    mapper = getattr(prop, "mapper", None)
    if mapper is None:
        return None
    return cast(type[Any], mapper.class_)


def _is_soft_delete(model: type[Any]) -> bool:
    # Local import — soft_deletes itself does not need to know about
    # QuerySet, but importing it at module load time would create a
    # subtle ordering dependency between the two files. Doing the import
    # here keeps queryset.py the single point of soft-delete awareness
    # for read paths.
    from pylar.database.soft_deletes import SoftDeletes

    return isinstance(model, type) and issubclass(model, SoftDeletes)
