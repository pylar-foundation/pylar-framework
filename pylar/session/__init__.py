"""Cookie-driven session storage layer.

A pylar session is the small bag of per-user data that survives across
HTTP requests — typically the authenticated user id, a CSRF nonce, a
flash bag of one-shot messages. The layer is split into three parts so
each piece can be replaced independently:

* :class:`SessionStore` Protocol — the storage backend. The bundled
  implementations are :class:`MemorySessionStore` (process-local,
  useful for tests and dev), :class:`FileSessionStore` (one JSON file
  per session id on disk), and :class:`RedisSessionStore` (Redis
  strings with server-side TTL, behind ``pylar[session-redis]``).
* :class:`SessionMiddleware` — the per-request glue. Reads the signed
  session id from the cookie (or generates a fresh one), loads the
  payload through the store, exposes a :class:`Session` object via the
  ``current_session`` context variable, and writes back any changes
  before the response leaves the kernel.
* :class:`Session` — the typed handle controllers and guards interact
  with. Implements ``get`` / ``put`` / ``forget`` / ``flash`` plus a
  ``regenerate()`` method that rotates the session id (used after
  login to defeat session-fixation attacks).

Cookies are signed with HMAC-SHA-256 over the secret-key configured in
:class:`SessionConfig`. The signature is verified on every request and
mismatches surface as a fresh anonymous session — pylar never trusts
unsigned ids.
"""

from pylar.session.config import SessionConfig
from pylar.session.context import current_session, current_session_or_none
from pylar.session.middleware import SessionMiddleware
from pylar.session.provider import SessionServiceProvider
from pylar.session.session import Session
from pylar.session.store import SessionStore
from pylar.session.stores.file import FileSessionStore
from pylar.session.stores.memory import MemorySessionStore

__all__ = [
    "FileSessionStore",
    "MemorySessionStore",
    "Session",
    "SessionConfig",
    "SessionMiddleware",
    "SessionServiceProvider",
    "SessionStore",
    "current_session",
    "current_session_or_none",
]
