"""HTTP middleware that loads / persists a :class:`Session` per request."""

from __future__ import annotations

import hashlib
import hmac
from uuid import uuid4

from pylar.http.middleware import RequestHandler
from pylar.http.request import Request
from pylar.http.response import Response
from pylar.session.config import SessionConfig
from pylar.session.context import _reset_session, _set_session
from pylar.session.session import Session
from pylar.session.store import SessionStore


class SessionMiddleware:
    """Read the cookie, load the payload, expose :class:`Session`, write back.

    The cookie value is ``<session_id>.<hmac_hex>``. The id is a 32-char
    UUID hex; the HMAC is signed with :class:`SessionConfig.secret_key`
    using SHA-256. On every request the middleware verifies the
    signature, refuses any tampered cookie, and either loads the
    matching payload from the store or starts a fresh anonymous
    session. After the inner handler runs, the middleware writes the
    session back through the store (if dirty), updates the cookie on
    the outgoing response, and resets the context variable so nothing
    leaks into the next request.
    """

    def __init__(self, store: SessionStore, config: SessionConfig) -> None:
        self._store = store
        self._config = config

    async def handle(
        self, request: Request, next_handler: RequestHandler
    ) -> Response:
        session_id = self._read_cookie(request)
        data: dict[str, object] = {}
        if session_id is not None:
            existing = await self._store.read(session_id)
            if existing is not None:
                data = dict(existing)
        if session_id is None:
            session_id = uuid4().hex

        session = Session(session_id, data)
        token = _set_session(session)
        try:
            response = await next_handler(request)
        finally:
            _reset_session(token)

        await self._persist(session)
        self._set_cookie(response, session)
        return response

    # ------------------------------------------------------------------ internals

    def _read_cookie(self, request: Request) -> str | None:
        raw = request.cookies.get(self._config.cookie_name)
        if not raw or "." not in raw:
            return None
        session_id, _, signature = raw.rpartition(".")
        expected = self._sign(session_id)
        if not hmac.compare_digest(expected, signature):
            return None
        return session_id

    def _sign(self, session_id: str) -> str:
        return hmac.new(
            self._config.secret_key.encode("utf-8"),
            session_id.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    async def _persist(self, session: Session) -> None:
        # Regeneration: drop the old id, then write under the new one.
        if session.regenerated_from is not None:
            await self._store.destroy(session.regenerated_from)
        if session.is_destroyed:
            await self._store.destroy(session.id)
            return
        if session.is_dirty or session.regenerated_from is not None:
            await self._store.write(
                session.id,
                session.to_payload(),
                ttl_seconds=self._config.lifetime_seconds,
            )

    def _set_cookie(self, response: Response, session: Session) -> None:
        if session.is_destroyed:
            response.delete_cookie(
                self._config.cookie_name,
                path=self._config.cookie_path,
                domain=self._config.cookie_domain,
            )
            return
        value = f"{session.id}.{self._sign(session.id)}"
        response.set_cookie(
            self._config.cookie_name,
            value,
            max_age=self._config.lifetime_seconds,
            path=self._config.cookie_path,
            domain=self._config.cookie_domain,
            secure=self._config.cookie_secure,
            httponly=self._config.cookie_http_only,
            samesite=self._config.cookie_same_site,
        )
