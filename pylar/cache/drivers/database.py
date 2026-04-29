"""SQLAlchemy-backed cache driver.

Persists cache entries into a single ``cache`` table on the same
database the application already uses. The big win over
:class:`FileCacheStore` is cross-process visibility: every worker that
shares the database sees the same cache without operating Redis. The
big tradeoff is that every cache hit costs a SQL round-trip, so this
driver is best for medium-frequency reads with expensive sources, not
for hot-path microsecond lookups.

The table schema is intentionally minimal — ``key`` (primary key),
``value`` (JSON-encoded blob), ``expires_at`` (nullable epoch
seconds). The driver creates the table on first use through
:meth:`bootstrap` so a fresh project does not have to write a
migration just to try the cache layer; for production deployments
the user typically pins the table into a normal Alembic migration.
"""

from __future__ import annotations

import json
import time
from typing import Any

from sqlalchemy import (
    BigInteger,
    Column,
    MetaData,
    String,
    Table,
    Text,
    delete,
    insert,
    select,
)
from sqlalchemy.ext.asyncio import AsyncEngine

# A standalone metadata object — the cache table is independent of the
# user's Model.metadata so it can be created without dragging the
# application's models into the same registry.
_metadata = MetaData()

cache_table = Table(
    "pylar_cache",
    _metadata,
    Column("key", String(255), primary_key=True),
    Column("value", Text, nullable=False),
    Column("expires_at", BigInteger, nullable=True),
)


class DatabaseCacheStore:
    """Cache driver backed by a single SQL table.

    *engine* is the same :class:`AsyncEngine` the rest of the
    application uses. The driver opens its own short-lived connections
    rather than borrowing the request-scoped session because cache
    operations should not interact with the user's transaction
    boundaries — flushing the cache mid-request must not roll back if
    the surrounding handler later raises.
    """

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def bootstrap(self) -> None:
        """Create the cache table if it does not yet exist.

        Idempotent — safe to call on every boot. Production deployments
        usually run an Alembic migration that materialises the same
        schema, in which case calling :meth:`bootstrap` is a no-op.
        """
        async with self._engine.begin() as conn:
            await conn.run_sync(_metadata.create_all)

    async def get(self, key: str) -> Any:
        async with self._engine.begin() as conn:
            row = (
                await conn.execute(
                    select(cache_table.c.value, cache_table.c.expires_at).where(
                        cache_table.c.key == key
                    )
                )
            ).first()
            if row is None:
                return None
            value, expires_at = row
            if expires_at is not None and time.time() >= expires_at:
                await conn.execute(
                    delete(cache_table).where(cache_table.c.key == key)
                )
                return None
            return json.loads(value)

    async def put(self, key: str, value: Any, *, ttl: int | None = None) -> None:
        encoded = json.dumps(value)
        expires_at = int(time.time() + ttl) if ttl is not None else None
        async with self._engine.begin() as conn:
            # Atomic upsert: DELETE + INSERT in a single transaction.
            # Cross-dialect safe (works on SQLite, Postgres, MySQL).
            await conn.execute(
                delete(cache_table).where(cache_table.c.key == key)
            )
            await conn.execute(
                insert(cache_table).values(
                    key=key, value=encoded, expires_at=expires_at
                )
            )

    async def forget(self, key: str) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                delete(cache_table).where(cache_table.c.key == key)
            )

    async def flush(self) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(delete(cache_table))
