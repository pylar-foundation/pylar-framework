"""Base class for every typed config schema in pylar."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class BaseConfig(BaseModel):
    """A frozen, strict pydantic model used for every config domain.

    Subclasses describe a single configuration aggregate (database, mail,
    queue, ...). Each user config module under ``myapp/config/`` instantiates
    one of these subclasses and exports it as the module-level ``config``
    attribute. The :class:`pylar.config.ConfigLoader` then binds every such
    instance into the container by its concrete type, so that providers can
    request it via plain dependency injection::

        class DatabaseServiceProvider(ServiceProvider):
            async def boot(self, container: Container) -> None:
                cfg = container.make(DatabaseConfig)
                ...
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        validate_assignment=True,
        arbitrary_types_allowed=True,
    )
