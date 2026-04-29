"""Database seeding — Laravel-style ``Seeder`` and the ``db:seed`` command.

A :class:`Seeder` is a small async class that knows how to insert
fixture rows. The user registers seeders in their ``DatabaseServiceProvider``
(or any other provider that runs early enough) by tagging them under
:data:`SEEDERS_TAG`. The bundled :class:`SeedCommand` resolves the
container, looks up every tagged seeder, and runs them in turn inside
a single ambient :func:`pylar.database.use_session` scope.

Example::

    from pylar.database import Seeder

    class UserSeeder(Seeder):
        async def run(self) -> None:
            for email in ("alice@example.com", "bob@example.com"):
                await User.query.save(User(email=email))

    class DatabaseServiceProvider(ServiceProvider):
        def register(self, container: Container) -> None:
            container.tag([UserSeeder], SEEDERS_TAG)

Then::

    pylar db:seed
"""

from __future__ import annotations

from abc import ABC, abstractmethod

#: Container tag under which :class:`Seeder` subclasses are registered.
SEEDERS_TAG = "database.seeders"


class Seeder(ABC):
    """A unit of database seeding.

    Subclasses are constructed by the container, so their ``__init__``
    can pull in services (mailers, hashers, configuration) the same way
    a controller would. The :meth:`run` method does the actual inserts
    against the ambient session installed by :func:`use_session`.
    """

    @abstractmethod
    async def run(self) -> None:
        """Insert seed rows into the active database session."""
