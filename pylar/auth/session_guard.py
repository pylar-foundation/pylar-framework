"""A :class:`Guard` implementation backed by the session layer.

The guard reads the authenticated user id out of the current
:class:`pylar.session.Session` and resolves it through a user-provider
callable. The provider returns the matching :class:`Authenticatable`
or ``None``; resolving the lookup itself is the application's job
because pylar deliberately does not pick a user model.

Login is :meth:`SessionGuard.login`. It writes the user id into the
session, regenerates the session id to defeat fixation, and remembers
the freshly authenticated user for the rest of the request.
``logout`` clears the slot.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import ClassVar

from pylar.auth.contracts import Authenticatable
from pylar.http.request import Request
from pylar.session.context import current_session_or_none

#: Callable that takes a user id and returns the matching user (or
#: ``None`` if the id no longer points anywhere — e.g. the user was
#: deleted between requests).
UserResolver = Callable[[object], Awaitable[Authenticatable | None]]


class SessionGuard[UserT: Authenticatable]:
    """Resolve the current user from the session payload.

    Bind through the container the way any guard would::

        container.singleton(Guard, lambda: SessionGuard(resolver))

    where ``resolver`` is an ``async def`` accepting an opaque id and
    returning the matching user. The session key under which the id
    lives is ``"_auth.user_id"`` by default; override
    :attr:`session_key` on a subclass if you need to share a session
    with another framework that uses a different convention.
    """

    session_key: str = "_auth.user_id"

    #: Maximum login attempts before the guard refuses further tries.
    #: Set to 0 to disable (not recommended). Tracked per session.
    max_attempts: ClassVar[int] = 5

    #: Seconds the user must wait after exceeding :attr:`max_attempts`.
    lockout_seconds: ClassVar[int] = 60

    def __init__(self, resolver: UserResolver) -> None:
        self._resolver = resolver

    async def authenticate(self, request: Request) -> Authenticatable | None:
        session = current_session_or_none()
        if session is None:
            return None
        user_id = session.get(self.session_key)
        if user_id is None:
            return None
        return await self._resolver(user_id)

    async def login(self, user: UserT) -> None:
        """Mark *user* as logged in for the rest of the request.

        Writes the user id to the session and regenerates the id to
        defeat session-fixation. Subsequent calls to :meth:`authenticate`
        within the same request still go through the resolver.
        """
        session = current_session_or_none()
        if session is None:
            raise RuntimeError(
                "SessionGuard.login() requires SessionMiddleware to "
                "be installed before AuthMiddleware."
            )
        self._clear_attempts(session)
        session.put(self.session_key, user.auth_identifier)
        session.regenerate()

    async def logout(self) -> None:
        """Clear the user slot from the session."""
        session = current_session_or_none()
        if session is None:
            return
        session.forget(self.session_key)
        session.regenerate()

    # --------------------------------------------------------- brute-force

    def record_failed_attempt(self) -> None:
        """Increment the failed-login counter in the current session.

        Call this from your login controller when authentication fails.
        """
        session = current_session_or_none()
        if session is None:
            return
        attempts = int(session.get("_auth.attempts", 0) or 0)
        session.put("_auth.attempts", attempts + 1)
        if attempts + 1 >= self.max_attempts:
            import time
            session.put("_auth.locked_until", time.time() + self.lockout_seconds)

    def is_locked_out(self) -> bool:
        """Return ``True`` if the user has exceeded :attr:`max_attempts`.

        Call this at the top of your login controller and return 429
        if True. The lockout clears automatically after
        :attr:`lockout_seconds` or after a successful :meth:`login`.
        """
        if self.max_attempts <= 0:
            return False
        session = current_session_or_none()
        if session is None:
            return False
        locked_until = session.get("_auth.locked_until")
        if locked_until is None:
            return False
        import time
        if time.time() >= float(locked_until):
            self._clear_attempts(session)
            return False
        return True

    def remaining_attempts(self) -> int:
        """Return how many login attempts remain before lockout."""
        if self.max_attempts <= 0:
            return 999
        session = current_session_or_none()
        if session is None:
            return self.max_attempts
        attempts = int(session.get("_auth.attempts", 0) or 0)
        return max(0, self.max_attempts - attempts)

    @staticmethod
    def _clear_attempts(session: object) -> None:
        from pylar.session.session import Session
        if isinstance(session, Session):
            session.forget("_auth.attempts")
            session.forget("_auth.locked_until")
