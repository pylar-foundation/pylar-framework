"""Laravel-style model lifecycle observers.

An :class:`Observer` is a plain class with twelve optional async hooks.
Pylar fires them from :meth:`Manager.save`, :meth:`Manager.delete`,
:meth:`Manager.force_delete`, and :meth:`Manager.restore` — never from
SQLAlchemy event hooks, because those are synchronous and would force
users to write blocking code in places where the rest of the framework
is async.

Bulk operations (``QuerySet.delete()``, ``QuerySet.force_delete()``, raw
``session.add() + flush``) bypass observers on purpose. This matches
Laravel's Eloquent semantics: lifecycle events fire for the explicit
single-instance path; bulk paths are the escape hatch when you know what
you are doing.

Hook order on save::

    saving → creating | updating → flush → created | updated → saved

Hook order on delete (regular model, hard delete)::

    deleting → flush → deleted

Hook order on delete (SoftDeletes model, soft delete)::

    deleting → UPDATE deleted_at → deleted

Hook order on force_delete (SoftDeletes model)::

    deleting → force_deleting → DELETE → force_deleted → deleted

Hook order on restore (SoftDeletes model)::

    restoring → UPDATE deleted_at = NULL → restored
"""

from __future__ import annotations


class Observer[ModelT]:
    """Override the hooks relevant to your use case. Defaults are no-ops."""

    async def saving(self, instance: ModelT) -> None: ...
    async def saved(self, instance: ModelT) -> None: ...

    async def creating(self, instance: ModelT) -> None: ...
    async def created(self, instance: ModelT) -> None: ...

    async def updating(self, instance: ModelT) -> None: ...
    async def updated(self, instance: ModelT) -> None: ...

    async def deleting(self, instance: ModelT) -> None: ...
    async def deleted(self, instance: ModelT) -> None: ...

    # ------------------------------------------------------- soft-delete hooks

    async def restoring(self, instance: ModelT) -> None: ...
    async def restored(self, instance: ModelT) -> None: ...

    async def force_deleting(self, instance: ModelT) -> None: ...
    async def force_deleted(self, instance: ModelT) -> None: ...
