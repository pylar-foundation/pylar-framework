"""Authentication configuration."""

from __future__ import annotations

from pylar.config import BaseConfig


class AuthConfig(BaseConfig):
    """Application-level auth configuration.

    ``user_model`` is the import path to the authenticatable model class.
    It defaults to pylar's built-in :class:`User` but can be swapped to
    any class satisfying the :class:`Authenticatable` protocol::

        # config/auth.py
        from pylar.auth import AuthConfig

        config = AuthConfig(
            user_model="app.models.user:CustomUser",
        )

    The format is ``"module.path:ClassName"`` — the same convention
    Python entry points use.  At boot time the auth provider resolves
    the string to an actual class and validates that it satisfies
    :class:`Authenticatable`.
    """

    user_model: str = "pylar.auth.user:User"
    password_hasher: str = "pbkdf2"  # "pbkdf2" or "argon2"
