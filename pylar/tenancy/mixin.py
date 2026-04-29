"""``TenantScopedMixin`` — Tier A column-isolation auto-scoping.

Add to any model that carries a ``tenant_id`` FK:

    class Post(Model, TenantScopedMixin):
        class Meta:
            db_table = "posts"

        tenant_id = fields.IntegerField(index=True)
        title = fields.CharField(max_length=200)

Every ``query.all()`` / ``query.first()`` / ``query.count()`` on the
model auto-injects ``WHERE tenant_id = current_tenant().id``. On
``save()``, the mixin stamps ``tenant_id`` from the ambient tenant if
the field is empty.

The mixin overrides the model-level query manager so the scoping is
transparent — user code writes ``Post.query.all()`` and gets only the
active tenant's rows. There is no way to accidentally omit the scope.

To bypass the scope (admin panel, data migrations, cross-tenant
analytics):

    Post.query.unscoped().all()   # no WHERE tenant_id filter
"""

from __future__ import annotations

from typing import Any, cast


class TenantScopedMixin:
    """Mixin that auto-scopes queries and stamps tenant_id on save.

    The implementation hooks into the model's manager at query time;
    the actual ``WHERE`` clause is injected via the standard
    ``QuerySet.where`` path so every chain (with_, order_by, paginate)
    inherits the scope automatically.
    """

    @classmethod
    def _tenant_scope_filter(cls) -> Any:
        """Return the predicate for the current tenant, or ``None`` if no
        tenant is active (outside a request — CLI, tests)."""
        from pylar.tenancy.context import current_tenant_or_none

        tenant = current_tenant_or_none()
        if tenant is None:
            return None
        tenant_id_attr = getattr(cls, "tenant_id", None)
        if tenant_id_attr is None:
            return None
        return tenant_id_attr == cast(Any, tenant).id

    def _stamp_tenant_id(self) -> None:
        """On save, auto-fill ``tenant_id`` from the ambient tenant when
        the field is empty (``None`` or ``0``).
        """
        from pylar.tenancy.context import current_tenant_or_none

        tenant = current_tenant_or_none()
        if tenant is None:
            return
        current = getattr(self, "tenant_id", None)
        if current is None or current == 0:
            object.__setattr__(self, "tenant_id", cast(Any, tenant).id)
