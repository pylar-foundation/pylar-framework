"""Service provider that wires the session layer."""

from __future__ import annotations

from pylar.foundation.container import Container
from pylar.foundation.provider import ServiceProvider
from pylar.session.config import SessionConfig
from pylar.session.middleware import SessionMiddleware
from pylar.session.store import SessionStore
from pylar.session.stores.memory import MemorySessionStore


class SessionServiceProvider(ServiceProvider):
    """Bind a default :class:`SessionStore` and the middleware factory.

    The provider falls back to :class:`MemorySessionStore` so the
    framework still has a working session backend out of the box;
    production deployments override the binding with
    :class:`FileSessionStore` or any custom :class:`SessionStore`
    implementation through their own service provider.

    When an :class:`Encrypter` is bound in the container (i.e.
    :class:`EncryptionServiceProvider` is registered and ``APP_KEY``
    is set) the provider automatically wraps the store in an
    :class:`EncryptedSessionStore` so session payloads are encrypted
    at rest — no manual wiring needed.
    """

    def register(self, container: Container) -> None:
        if not container.has(SessionStore):
            container.singleton(SessionStore, MemorySessionStore)  # type: ignore[type-abstract]
        container.bind(SessionMiddleware, self._make_middleware)

    def _make_middleware(self) -> SessionMiddleware:
        import logging

        store = self.app.container.make(SessionStore)  # type: ignore[type-abstract]
        config = self.app.container.make(SessionConfig)
        # Auto-harden: force cookie_secure=True in production (debug=False).
        if not self.app.config.debug and not config.cookie_secure:
            config = config.model_copy(update={"cookie_secure": True})
            logging.getLogger("pylar.session").warning(
                "cookie_secure auto-upgraded to True because debug=False. "
                "Pass cookie_secure=True explicitly to silence this warning."
            )
        store = self._maybe_encrypt(store)
        return SessionMiddleware(store, config)

    def _maybe_encrypt(self, store: SessionStore) -> SessionStore:
        """Wrap *store* in encryption if an Encrypter is available."""
        from pylar.encryption.encrypter import Encrypter
        from pylar.session.encrypted_store import EncryptedSessionStore

        if not self.app.container.has(Encrypter):
            return store
        encrypter = self.app.container.make(Encrypter)
        return EncryptedSessionStore(inner=store, encrypter=encrypter)
