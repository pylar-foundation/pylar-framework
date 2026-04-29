"""Async transaction helper around the ambient session."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from pylar.database.session import current_session


@asynccontextmanager
async def transaction(
    *, isolation_level: str | None = None,
) -> AsyncIterator[AsyncSession]:
    """Run a block inside an explicit database transaction.

    The helper requires an active session — call :func:`use_session`
    (or rely on ``DatabaseSessionMiddleware``) before entering. On
    normal exit the transaction is committed; on any exception it is
    rolled back and the exception is re-raised.

    Pass *isolation_level* (e.g. ``"SERIALIZABLE"``,
    ``"REPEATABLE READ"``) to override the database default for this
    transaction::

        async with transaction(isolation_level="SERIALIZABLE") as session:
            ...
    """
    session = current_session()
    if isolation_level is not None:
        conn = await session.connection()
        await conn.execution_options(isolation_level=isolation_level)
    try:
        yield session
    except Exception:
        await session.rollback()
        raise
    else:
        await session.commit()
