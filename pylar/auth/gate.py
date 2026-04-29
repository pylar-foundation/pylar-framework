"""The :class:`Gate` — central authorization registry.

The gate accepts authorization checks in two flavours that mirror Laravel:

* **Policy checks** route to a :class:`Policy` registered for the type of
  the *first* argument. ``gate.allows(user, "view", post)`` looks up the
  ``Policy`` for ``Post``, then calls its ``view`` method with
  ``(user, post)``. ``gate.allows(user, "view_any", Post)`` works against
  the class itself.

* **Ability checks** route to a callable registered with :meth:`define`.
  ``gate.allows(user, "access-admin")`` calls the callback with ``user``
  and any extra arguments.

Both ``allows`` and ``authorize`` are async because policy methods are async
— a real authorization check often needs to load data from the database.
:meth:`authorize` raises :class:`AuthorizationError` on failure so that the
route compiler can convert it into a 403 response.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from pylar.auth.exceptions import AuthorizationError
from pylar.auth.policy import Policy

#: Signature of an ability callback registered via :meth:`Gate.define`.
AbilityCallback = Callable[..., Awaitable[bool]]


class Gate:
    """Central registry of policies and standalone abilities."""

    def __init__(self) -> None:
        self._policies: dict[type[Any], Policy[Any]] = {}
        self._abilities: dict[str, AbilityCallback] = {}

    # ----------------------------------------------------------------- registry

    def policy(self, model: type[Any], policy: Policy[Any]) -> None:
        """Register *policy* as the authorization handler for *model*."""
        self._policies[model] = policy

    def define(self, ability: str, callback: AbilityCallback) -> None:
        """Register a standalone ability callback."""
        self._abilities[ability] = callback

    def has_policy(self, model: type[Any]) -> bool:
        return model in self._policies

    def has_ability(self, ability: str) -> bool:
        return ability in self._abilities

    # ------------------------------------------------------------------- checks

    async def allows(self, user: Any, ability: str, *args: object) -> bool:
        """Return ``True`` if *user* is permitted to perform *ability*.

        When *args* contains a model class or instance, the gate looks up the
        policy registered for that type. The policy method is then invoked
        with the *correct* number of arguments — class-level abilities such
        as ``view_any`` and ``create`` receive only the user, instance-level
        abilities such as ``view`` and ``update`` receive ``(user, instance)``.
        """
        if args:
            target = args[0]
            policy = self._lookup_policy(target)
            if policy is not None:
                method = getattr(policy, ability, None)
                if method is None:
                    return False
                signature = inspect.signature(method)
                # Bound-method signature excludes self; the first parameter is
                # always the user. Anything beyond that is an instance arg.
                instance_arg_count = max(len(signature.parameters) - 1, 0)
                if instance_arg_count == 0:
                    return bool(await method(user))
                if isinstance(target, type):
                    # The caller supplied a class, but the policy method
                    # expects an instance. Treat this as denied rather than
                    # silently passing the class through.
                    return False
                return bool(await method(user, *args[:instance_arg_count]))

        callback = self._abilities.get(ability)
        if callback is not None:
            return bool(await callback(user, *args))

        return False

    async def denies(self, user: Any, ability: str, *args: object) -> bool:
        return not await self.allows(user, ability, *args)

    async def authorize(self, user: Any, ability: str, *args: object) -> None:
        """Raise :class:`AuthorizationError` unless the check passes."""
        if not await self.allows(user, ability, *args):
            raise AuthorizationError(ability)

    # ------------------------------------------------------------------ internals

    def _lookup_policy(self, target: object) -> Policy[Any] | None:
        """Find the policy registered for *target* (an instance or a class)."""
        target_type = target if isinstance(target, type) else type(target)
        for klass in target_type.__mro__:
            if klass in self._policies:
                return self._policies[klass]
        return None
