# database/ — backlog

The database read-side polish landed:

* :class:`F` and :class:`Q` — composable, model-aware predicates that
  compile down to SQLAlchemy ``ColumnElement[bool]`` at
  ``QuerySet.where`` time. ``Q(active=True) | Q(role="admin")``,
  ``F("login_count") > 10``, and ``~Q(banned=True)`` all read like
  Python and combine with the usual boolean operators.
* Django-style lookup suffixes on the kwargs form — ``Q(name__icontains="al")``,
  ``Q(id__in=[1, 2, 3])``, ``Q(deleted_at__isnull=True)`` etc.
* :meth:`QuerySet.with_` — eager-loads relationships through
  ``selectinload`` so awaited handlers do not trip the SA lazy-loading
  guard. Single-level (``with_("author")``), multi-relation
  (``with_("author", "tags")``), and dotted nested paths
  (``with_("post.author")``) are all supported. Chains accumulate.

What is still on the wishlist:

## Schema builder DSL

For users that prefer Laravel-style table definitions over SQLAlchemy
`Mapped[...]`:

```python
schema.create("posts", lambda table: (
    table.id(),
    table.string("title", length=200),
    table.text("body").nullable(),
    table.timestamps(),
))
```

This is a convenience layer that generates SQLAlchemy `Table` objects under
the hood. Worth reconsidering whether it carries its weight — the typed
`Mapped[...]` syntax is already very good.

## ~~Relationship layer~~ ✓

Three relationship field types landed:

* ``fields.BelongsTo(to=..., model=...)`` — FK column + relationship()
  in one declaration (many-to-one).
* ``fields.HasMany(model=..., back_populates=...)`` — reverse
  one-to-many relationship (no column created).
* ``fields.HasOne(model=..., back_populates=...)`` — reverse
  one-to-one relationship (uselist=False).

The metaclass processes ``RelationshipField`` instances separately
from column ``Field`` instances. ``BelongsTo`` expands to both a
``mapped_column(ForeignKey(...))`` and a ``relationship()``.

## ManyToMany

Still deferred. A real M2M field would generate the join-table
model on the fly and bind ``relationship(secondary=...)`` to both
sides; that requires the metaclass to route relationship declarations
through SA's configuration phase, which is its own design exercise.

## HstoreField

Postgres ``hstore`` key-value columns behind a ``pylar[postgres]``
extra. Niche enough that it can wait for the first user that asks
for it.
