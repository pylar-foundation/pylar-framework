"""Ambient :class:`AsyncSession` exposed via a context variable.

Pylar avoids facades, but it would be painful to thread a session argument
through every controller and service. The compromise is a single
:class:`contextvars.ContextVar` that holds the active session for the current
asynchronous task. The HTTP middleware (or :func:`use_session` for tests and
CLI commands) is responsible for opening that scope.

Code that runs queries calls :func:`current_session` and gets back the live
session — or a clear :class:`NoActiveSessionError` if no scope is open. There
is no implicit fallback to "the default session" anywhere.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar

from sqlalchemy.ext.asyncio import AsyncSession

from pylar.database.connection import ConnectionManager
from pylar.database.exceptions import NoActiveSessionError

_current_session: ContextVar[AsyncSession | None] = ContextVar(
    "pylar_current_session", default=None
)


def current_session() -> AsyncSession:
    """Return the active session for this task, or raise :class:`NoActiveSessionError`."""
    session = _current_session.get()
    if session is None:
        raise NoActiveSessionError(
            "No active database session. Wrap your code in `async with use_session(manager):` "
            "or run it inside a request handled by DatabaseSessionMiddleware."
        )
    return session


def current_session_or_none() -> AsyncSession | None:
    """Return the active session, or ``None`` if no session is open."""
    return _current_session.get()


@asynccontextmanager
async def use_session(manager: ConnectionManager) -> AsyncIterator[AsyncSession]:
    """Open a session, install it into the contextvar, then close it on exit.

    The session is **not** committed automatically — that is the caller's job
    or the transaction helper's job. This mirrors SQLAlchemy's expectations and
    keeps the boundary between read and write paths explicit.
    """
    session = manager.session()
    token = _current_session.set(session)
    try:
        yield session
    except BaseException:
        await session.rollback()
        raise
    finally:
        _current_session.reset(token)
        await session.close()


@asynccontextmanager
async def ambient_session(manager: ConnectionManager) -> AsyncIterator[AsyncSession | None]:
    """Ensure an ambient session is available for the duration of the block.

    This is the hook that runtime surfaces — the HTTP middleware, the
    queue :class:`Worker`, the :class:`SchedulerKernel`, and the console
    kernel — use so that user code can rely on ``current_session()``
    without manually threading a session through every call site.

    If a session is already installed (e.g. the caller is nested inside
    another runtime surface), the inner scope reuses it and yields it
    unchanged. Otherwise a fresh session is opened on *manager*,
    installed into the contextvar, yielded, and closed on exit.
    """
    existing = _current_session.get()
    if existing is not None:
        yield existing
        return
    async with use_session(manager) as session:
        yield session


@asynccontextmanager
async def override_session(session: AsyncSession) -> AsyncIterator[AsyncSession]:
    """Install *session* as the current one for the duration of the block.

    Used by tests that already own a session (e.g. one rolled back at teardown
    to keep the database clean) and by the transaction helper to nest scopes.
    """
    token = _current_session.set(session)
    try:
        yield session
    finally:
        _current_session.reset(token)
