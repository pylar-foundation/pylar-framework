"""Per-model authorization policies — Laravel-style.

A :class:`Policy` is a plain class with a few async methods. Each method
returns ``True`` if the supplied user is allowed to perform the named action
against the (optional) model instance. The defaults all return ``False``
(deny by default), so a subclass only has to override the abilities it
actually grants.

Policies are registered on a :class:`Gate` together with the model class
they protect. The gate then knows to consult ``UserPolicy`` whenever an
authorization check involves a ``User`` instance.
"""

from __future__ import annotations

from typing import Any


class Policy[ModelT]:
    """Override only the abilities you grant; everything else is denied.

    The ``user`` parameter is intentionally typed as :class:`Any` so that
    subclasses can narrow it to a concrete user model without violating LSP.
    The base methods are no-ops that return ``False``.
    """

    async def view_any(self, user: Any) -> bool:
        return False

    async def view(self, user: Any, instance: ModelT) -> bool:
        return False

    async def create(self, user: Any) -> bool:
        return False

    async def update(self, user: Any, instance: ModelT) -> bool:
        return False

    async def delete(self, user: Any, instance: ModelT) -> bool:
        return False

    async def restore(self, user: Any, instance: ModelT) -> bool:
        return False

    async def force_delete(self, user: Any, instance: ModelT) -> bool:
        return False
