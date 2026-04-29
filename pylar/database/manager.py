"""Per-model entry point: ``User.query.where(...).first()``."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import ColumnElement
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession

from pylar.database.expressions import Q
from pylar.database.observer import Observer
from pylar.database.paginator import Paginator
from pylar.database.queryset import QuerySet
from pylar.database.session import current_session
from pylar.database.soft_deletes import SoftDeletes

_logger = logging.getLogger("pylar.database.observer")

class Manager[ModelT]:
    """The query entry point bound to a single model class.

    The :class:`Manager` is intentionally thin: every chain operator is
    delegated to a fresh :class:`QuerySet`. Pylar attaches a manager to each
    :class:`Model` subclass automatically via ``__init_subclass__``, so user
    code reads as ``await User.query.where(User.email == "x@y").first()``.

    The manager also exposes write helpers (``save``, ``delete``,
    ``force_delete``, ``restore``) that operate on a single instance —
    bulk writes go through the underlying QuerySet. When the model
    inherits :class:`SoftDeletes`, the single-instance helpers behave the
    Laravel way: ``delete`` is soft, ``force_delete`` is permanent,
    ``restore`` clears the tombstone.
    """

    def __init__(self, model: type[ModelT]) -> None:
        self._model = model

    @property
    def model(self) -> type[ModelT]:
        return self._model

    @property
    def sync(self) -> Any:
        """Return a synchronous façade for scripts and REPL use.

        Each method blocks and returns a result directly instead of a
        coroutine::

            posts = Post.query.sync.all()
            post = Post.query.sync.get(1)
            Post.query.sync.save(post)

        Chain operators also return a sync facade so entire chains
        stay synchronous::

            Post.query.sync.where(Post.published.is_(True)).first()
        """
        from pylar.database.sync_manager import SyncManager

        return SyncManager(self)

    # ----------------------------------------------------------- chain operators

    def where(
        self, *conditions: ColumnElement[bool] | Q
    ) -> QuerySet[ModelT]:
        return QuerySet.for_model(self._model).where(*conditions)

    def order_by(self, *expressions: ColumnElement[object]) -> QuerySet[ModelT]:
        return QuerySet.for_model(self._model).order_by(*expressions)

    def limit(self, n: int) -> QuerySet[ModelT]:
        return QuerySet.for_model(self._model).limit(n)

    def offset(self, n: int) -> QuerySet[ModelT]:
        return QuerySet.for_model(self._model).offset(n)

    def with_(self, *relations: str) -> QuerySet[ModelT]:
        """Open a chain that eager-loads the named relationships."""
        return QuerySet.for_model(self._model).with_(*relations)

    def with_trashed(self) -> QuerySet[ModelT]:
        """Open a chain that includes soft-deleted rows."""
        return QuerySet.for_model(self._model).with_trashed()

    def only_trashed(self) -> QuerySet[ModelT]:
        """Open a chain that returns only soft-deleted rows."""
        return QuerySet.for_model(self._model).only_trashed()

    # ------------------------------------------------------------ direct reads

    async def all(self, *, session: AsyncSession | None = None) -> list[ModelT]:
        return await QuerySet.for_model(self._model).all(session=session)

    async def first(self, *, session: AsyncSession | None = None) -> ModelT | None:
        return await QuerySet.for_model(self._model).first(session=session)

    async def get(self, primary_key: object, *, session: AsyncSession | None = None) -> ModelT:
        return await QuerySet.for_model(self._model).get(primary_key, session=session)

    async def count(self, *, session: AsyncSession | None = None) -> int:
        return await QuerySet.for_model(self._model).count(session=session)

    async def paginate(
        self,
        *,
        page: int = 1,
        per_page: int = 15,
        path: str = "",
        query_params: dict[str, str] | None = None,
        session: AsyncSession | None = None,
    ) -> Paginator[ModelT]:
        return await QuerySet.for_model(self._model).paginate(
            page=page,
            per_page=per_page,
            path=path,
            query_params=query_params,
            session=session,
        )

    # ----------------------------------------------------------- single-row writes

    async def save(self, instance: ModelT, *, session: AsyncSession | None = None) -> ModelT:
        """Persist *instance* into the current session and flush.

        Fires the model's lifecycle observers around the flush:
        ``saving → creating|updating → flush → created|updated → saved``.
        ``save`` does **not** commit — that is the responsibility of the
        surrounding transaction. The flush makes server-generated columns
        (auto-increment ids, defaults) visible immediately.
        """
        sess = session if session is not None else current_session()
        observers = self._get_observers()
        state = sa_inspect(instance, raiseerr=True)
        # `inspect(instance, raiseerr=True)` always returns an InstanceState
        # for a mapped instance — `assert` narrows the Optional for mypy.
        assert state is not None
        is_new = not state.has_identity

        for observer in observers:
            await _safe_call(observer.saving, instance)
            if is_new:
                await _safe_call(observer.creating, instance)
            else:
                await _safe_call(observer.updating, instance)

        sess.add(instance)
        await sess.flush()

        for observer in observers:
            if is_new:
                await _safe_call(observer.created, instance)
            else:
                await _safe_call(observer.updated, instance)
            await _safe_call(observer.saved, instance)

        return instance

    async def delete(self, instance: ModelT, *, session: AsyncSession | None = None) -> None:
        """Delete *instance* — soft for SoftDeletes models, hard otherwise.

        For a model that inherits :class:`SoftDeletes`, this sets
        ``deleted_at`` to the current timestamp and flushes; the row stays
        in the database. The ``deleting``/``deleted`` observer hooks fire
        the same way they would for a hard delete, so observer code can
        treat both paths uniformly. Use :meth:`force_delete` when you
        really want to remove the row.
        """
        sess = session if session is not None else current_session()
        observers = self._get_observers()

        for observer in observers:
            await _safe_call(observer.deleting, instance)

        if self._is_soft_delete():
            # Soft delete: mark the tombstone and flush.
            cast_instance: SoftDeletes = instance  # type: ignore[assignment]
            cast_instance.deleted_at = datetime.now(UTC)
            sess.add(cast_instance)
            await sess.flush()
        else:
            await sess.delete(instance)
            await sess.flush()

        for observer in observers:
            await _safe_call(observer.deleted, instance)

    async def force_delete(
        self, instance: ModelT, *, session: AsyncSession | None = None
    ) -> None:
        """Permanently remove *instance* from the database.

        Equivalent to :meth:`delete` for non-soft-delete models. For
        soft-delete models the row is physically dropped instead of
        having its tombstone updated. Hook order matches Laravel:

            deleting → force_deleting → DELETE → force_deleted → deleted
        """
        sess = session if session is not None else current_session()
        observers = self._get_observers()

        for observer in observers:
            await _safe_call(observer.deleting, instance)
            await _safe_call(observer.force_deleting, instance)

        await sess.delete(instance)
        await sess.flush()

        for observer in observers:
            await _safe_call(observer.force_deleted, instance)
            await _safe_call(observer.deleted, instance)

    async def restore(
        self, instance: ModelT, *, session: AsyncSession | None = None
    ) -> ModelT:
        """Clear ``deleted_at`` on a soft-deleted instance.

        Raises :class:`TypeError` for models that do not mix in
        :class:`SoftDeletes` — restoring a hard-deleted row makes no
        sense and silently no-oping would mask the bug.
        """
        if not self._is_soft_delete():
            raise TypeError(
                f"{self._model.__qualname__} does not use SoftDeletes and "
                "cannot be restored"
            )

        sess = session if session is not None else current_session()
        observers = self._get_observers()

        for observer in observers:
            await _safe_call(observer.restoring, instance)

        cast_instance: SoftDeletes = instance  # type: ignore[assignment]
        cast_instance.deleted_at = None
        sess.add(cast_instance)
        await sess.flush()

        for observer in observers:
            await _safe_call(observer.restored, instance)

        return instance

    # ------------------------------------------------------------------ internals

    def _is_soft_delete(self) -> bool:
        return issubclass(self._model, SoftDeletes)

    def _get_observers(self) -> tuple[Observer[Any], ...]:
        observers_method = getattr(self._model, "observers", None)
        if observers_method is None:
            return ()
        result: tuple[Observer[Any], ...] = tuple(observers_method())
        return result


async def _safe_call(hook: Any, instance: Any) -> None:
    """Call an observer *hook* and log instead of crashing on failure."""
    try:
        await hook(instance)
    except Exception:
        _logger.exception(
            "Observer hook %s.%s raised — continuing",
            type(hook.__self__).__qualname__ if hasattr(hook, "__self__") else "?",
            hook.__name__ if hasattr(hook, "__name__") else "?",
        )
