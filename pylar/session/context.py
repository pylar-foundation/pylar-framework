"""Context-variable plumbing for the per-request :class:`Session`."""

from __future__ import annotations

from contextvars import ContextVar

from pylar.session.session import Session

_current_session: ContextVar[Session | None] = ContextVar(
    "pylar_current_session", default=None
)


def current_session() -> Session:
    """Return the active :class:`Session`, raising if none is bound.

    Mirrors :func:`pylar.auth.current_user` — call from inside a
    request scope and you get a typed handle; call outside one and
    you get a clear error rather than ``None``-induced failures
    deeper in the stack.
    """
    session = _current_session.get()
    if session is None:
        raise RuntimeError(
            "No active session — install SessionMiddleware before "
            "calling current_session()."
        )
    return session


def current_session_or_none() -> Session | None:
    """Return the active session or ``None`` outside a session scope."""
    return _current_session.get()


def _set_session(session: Session | None) -> object:
    """Internal helper used by :class:`SessionMiddleware`."""
    return _current_session.set(session)


def _reset_session(token: object) -> None:
    _current_session.reset(token)  # type: ignore[arg-type]
