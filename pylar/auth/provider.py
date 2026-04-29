"""AuthServiceProvider — wires authentication into the application.

Resolves the configured user model, binds the password hasher, and
registers a default :class:`SessionGuard` backed by a model lookup.
Applications can override any binding in their own provider.
"""

from __future__ import annotations

import importlib
import logging
from typing import Any

from pylar.auth.config import AuthConfig
from pylar.auth.contracts import Authenticatable, Guard
from pylar.auth.gate import Gate
from pylar.auth.hashing import PasswordHasher, Pbkdf2PasswordHasher
from pylar.auth.session_guard import SessionGuard
from pylar.auth.signed import UrlSigner
from pylar.foundation.container import Container
from pylar.foundation.provider import ServiceProvider

_logger = logging.getLogger("pylar.auth")


class AuthServiceProvider(ServiceProvider):
    """Register authentication services.

    During ``register`` (sync):
    * Resolves ``AuthConfig.user_model`` to a class
    * Binds ``AuthConfig``, ``PasswordHasher``, ``Gate``
    * Stores the resolved user model class for ``boot``

    During ``boot`` (async):
    * Registers a ``SessionGuard`` with a ``UserResolver`` that queries
      the configured user model by primary key
    * Applications can override the ``Guard`` binding before or after
      boot to use a different guard strategy
    """

    def register(self, container: Container) -> None:
        # Load auth config — look for config/auth.py in the project,
        # fall back to defaults.
        config = self._load_config(container)
        container.instance(AuthConfig, config)

        # Resolve the user model class from the config string.
        user_cls = _resolve_class(config.user_model)
        if user_cls is None:
            _logger.warning(
                "Could not resolve user model %r — auth will be limited",
                config.user_model,
            )
            return

        # Store on the provider instance for boot().
        self._user_cls: type[Any] = user_cls

        # Password hasher.
        if config.password_hasher == "argon2":
            try:
                from pylar.auth.hashing import Argon2PasswordHasher

                container.singleton(
                    PasswordHasher, Argon2PasswordHasher  # type: ignore[type-abstract]
                )
            except ImportError:
                _logger.warning("argon2-cffi not installed, falling back to pbkdf2")
                container.singleton(
                    PasswordHasher, Pbkdf2PasswordHasher  # type: ignore[type-abstract]
                )
        else:
            container.singleton(
                PasswordHasher, Pbkdf2PasswordHasher  # type: ignore[type-abstract]
            )

        # Gate (empty — policies registered by the app provider).
        if not container.has(Gate):
            container.singleton(Gate, Gate)

        # URL signer — HMAC-signed links for email verification,
        # password reset, and any user-facing signed-URL flow.
        # Keyed on APP_KEY so rotating the key invalidates every
        # outstanding link.
        if not container.has(UrlSigner):
            container.singleton(UrlSigner, self._make_signer)

    def _make_signer(self) -> UrlSigner:
        from pylar.config import env

        return UrlSigner(key=env.str("APP_KEY", "pylar-dev-insecure-signer-key"))

    async def boot(self, container: Container) -> None:
        user_cls = getattr(self, "_user_cls", None)
        if user_cls is None:
            return

        # Register a default SessionGuard if no Guard is bound yet.
        if not container.has(Guard):
            async def resolve_user(user_id: object) -> Authenticatable | None:
                """Default UserResolver — queries the user model by PK."""
                from pylar.database.session import current_session_or_none

                session = current_session_or_none()
                if session is None:
                    return None
                try:
                    return await user_cls.query.get(  # type: ignore[no-any-return]
                        user_id, session=session
                    )
                except Exception:
                    # Roll back so PostgreSQL exits the failed transaction
                    # state and subsequent queries on this session still work.
                    await session.rollback()
                    return None

            guard: SessionGuard[Any] = SessionGuard(resolver=resolve_user)
            container.instance(Guard, guard)  # type: ignore[type-abstract]

    def _load_config(self, container: Container) -> AuthConfig:
        """Try to load config/auth.py from the project, else use defaults."""
        try:
            module = importlib.import_module("config.auth")
            config = getattr(module, "config", None)
            if isinstance(config, AuthConfig):
                return config
        except (ImportError, ModuleNotFoundError):
            pass
        return AuthConfig()


def _resolve_class(dotted: str) -> type[Any] | None:
    """Resolve ``"module.path:ClassName"`` to a class object."""
    if ":" not in dotted:
        return None
    module_path, class_name = dotted.rsplit(":", 1)
    try:
        module = importlib.import_module(module_path)
        return getattr(module, class_name, None)
    except (ImportError, ModuleNotFoundError):
        return None
