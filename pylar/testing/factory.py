"""Typed model factories — pylar's answer to factory_boy."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from itertools import count
from typing import Any, ClassVar

from pylar.database.manager import Manager
from pylar.database.model import Model


def fake() -> Any:
    """Return a :class:`faker.Faker` instance for use in factory definitions.

    Lazily imports ``faker`` so the dependency stays optional behind
    ``pylar[faker]``. Raises :class:`ImportError` with an install hint
    when the package is missing::

        from pylar.testing import fake

        class UserFactory(Factory[User]):
            _faker = fake()

            def definition(self) -> dict[str, object]:
                return {
                    "name": self._faker.name(),
                    "email": self._faker.email(),
                }
    """
    try:
        from faker import Faker
    except ImportError:
        raise ImportError(
            "fake() requires the 'faker' package. "
            "Install with: pip install 'pylar[faker]'"
        ) from None
    return Faker()


class Sequence:
    """Counter that yields a unique value per call.

    Drop into a factory's :meth:`Factory.definition` to ensure each
    generated row has a distinct value::

        class UserFactory(Factory[User]):
            email_seq = Sequence(lambda n: f"user-{n}@example.com")

            def definition(self) -> dict[str, object]:
                return {"email": self.email_seq.next(), "name": "Test"}

    Each :class:`Sequence` instance has its own counter; reusing the
    same counter across factory instances is intentional.
    """

    def __init__(self, builder: Callable[[int], Any] | None = None) -> None:
        self._counter = count(1)
        self._builder = builder or (lambda n: n)

    def next(self) -> Any:
        return self._builder(next(self._counter))


class Factory[ModelT: Model](ABC):
    """Build :class:`Model` instances for tests with sensible defaults.

    Subclasses declare the model they build via the :meth:`model_class`
    classmethod and the field defaults via :meth:`definition`. The two
    factory entry points are :meth:`make` (constructs an instance with
    no persistence) and :meth:`create` (constructs and saves through
    the model's :class:`Manager`, returning the persisted instance with
    server-generated columns populated).

    Both entry points accept an ``overrides`` dict so individual tests
    can override specific fields without redefining the whole factory::

        user = await UserFactory().create(overrides={"email": "alice@example.com"})
    """

    @classmethod
    @abstractmethod
    def model_class(cls) -> type[ModelT]:
        """Return the :class:`Model` subclass this factory builds."""

    @abstractmethod
    def definition(self) -> dict[str, object]:
        """Return the default field values for one instance.

        Called every time :meth:`make` or :meth:`create` runs, so
        sequence-style defaults (counters, faker output) can produce
        unique values per call.
        """

    #: Optional named *traits* — a mapping of trait name to override
    #: dict that callers can opt into via :meth:`with_trait`. Useful
    #: for "an admin user" / "a soft-deleted post" sub-flavours.
    traits: ClassVar[dict[str, dict[str, object]]] = {}

    def __init__(self) -> None:
        self._extra_overrides: dict[str, object] = {}

    def with_trait(self, name: str) -> Factory[ModelT]:
        """Apply the named trait's overrides to subsequent ``make`` / ``create`` calls.

        Returns a *new* factory instance so chaining stays immutable.
        """
        if name not in self.traits:
            raise KeyError(
                f"{type(self).__qualname__} has no trait {name!r}. "
                f"Defined: {sorted(self.traits)}"
            )
        clone = type(self)()
        clone._extra_overrides = {**self._extra_overrides, **self.traits[name]}
        return clone

    def make(self, overrides: dict[str, object] | None = None) -> ModelT:
        """Construct an in-memory instance without persisting it."""
        attributes = {
            **self.definition(),
            **self._extra_overrides,
            **(overrides or {}),
        }
        return self.model_class()(**attributes)

    async def create(self, overrides: dict[str, object] | None = None) -> ModelT:
        """Construct *and* save an instance through its model's :class:`Manager`."""
        instance = self.make(overrides)
        manager: Manager[ModelT] = self.model_class().query
        return await manager.save(instance)

    def make_many(
        self, count: int, overrides: dict[str, object] | None = None
    ) -> list[ModelT]:
        """Build *count* in-memory instances."""
        return [self.make(overrides) for _ in range(count)]

    async def create_many(
        self, count: int, overrides: dict[str, object] | None = None
    ) -> list[ModelT]:
        """Build *and persist* *count* instances."""
        return [await self.create(overrides) for _ in range(count)]
