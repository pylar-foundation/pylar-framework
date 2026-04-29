"""Auto-managed timestamp columns — pylar's analogue of Laravel's Timestamps trait.

A model that mixes :class:`TimestampsMixin` in alongside :class:`Model`
gains two non-nullable columns:

* ``created_at`` — set to the current UTC moment when the row is first
  inserted.
* ``updated_at`` — set on insert and bumped automatically on every
  ``UPDATE`` via SQLAlchemy's native ``onupdate`` mechanism, so user
  code does not have to remember to touch the column on save.

Both timestamps are timezone-aware and use the framework's
``datetime.now(UTC)`` factory so the values stored on disk are always
unambiguous.

Composes through ordinary multiple inheritance::

    class Post(Model, TimestampsMixin):
        title = fields.CharField(max_length=200)
        body = fields.TextField()

The mixin is independent of :class:`SoftDeletes` and the two compose
freely::

    class Article(Model, TimestampsMixin, SoftDeletes):
        ...
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column


def _utc_now() -> datetime:
    return datetime.now(UTC)


class TimestampsMixin:
    """Adds automatic ``created_at`` / ``updated_at`` columns."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utc_now,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utc_now,
        onupdate=_utc_now,
        nullable=False,
    )
