"""Laravel-style :class:`SoftDeletes` mixin.

A model that mixes :class:`SoftDeletes` in alongside :class:`Model` gains
a nullable ``deleted_at`` column and a small set of helpers. The rest of
the database layer notices the inheritance and adapts:

* :class:`QuerySet` excludes rows with ``deleted_at IS NOT NULL`` from
  the default chain unless the caller switches to ``with_trashed()`` or
  ``only_trashed()``.
* :meth:`Manager.delete` performs a soft delete (sets ``deleted_at``)
  for soft-delete models and a hard delete for everything else.
* :meth:`Manager.force_delete` and :meth:`Manager.restore` provide the
  Laravel-equivalent escape hatches.
* Bulk :meth:`QuerySet.delete` translates into ``UPDATE deleted_at = now()``
  for soft-delete models; :meth:`QuerySet.force_delete` is the bulk
  version of the hard escape hatch.

Usage::

    from pylar.database import Model, SoftDeletes

    class Post(Model, SoftDeletes):
        __tablename__ = "posts"
        id: Mapped[int] = mapped_column(primary_key=True)
        title: Mapped[str]
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column


class SoftDeletes:
    """Mixin that adds a nullable ``deleted_at`` column and a trashed check.

    SQLAlchemy's declarative mapper picks the column up via the typed
    ``Mapped`` annotation, exactly the same way it would on a regular
    model attribute. The mixin is intentionally a plain class — not a
    metaclass and not a ``DeclarativeBase`` subclass — so it composes
    with :class:`Model` through normal multiple inheritance.
    """

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )

    def trashed(self) -> bool:
        """Return ``True`` when this row has been soft-deleted."""
        return self.deleted_at is not None
