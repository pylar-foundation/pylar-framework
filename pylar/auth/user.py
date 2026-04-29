"""Built-in :class:`User` model — the default authenticatable entity.

This is pylar's equivalent of Laravel's ``App\\Models\\User``.  It satisfies
the :class:`Authenticatable` protocol out of the box and ships with the
fields every application needs: name, email, password hash, and an admin
flag.

Applications extend the model by subclassing::

    from pylar.auth import User as BaseUser

    class User(BaseUser):
        class Meta:
            db_table = "users"

        phone = fields.CharField(max_length=20, null=True)
        avatar_url = fields.URLField(null=True)

Or replace it entirely via ``AuthConfig.user_model`` — any class that
satisfies :class:`Authenticatable` works.
"""

from __future__ import annotations

from typing import Any, cast

from pylar.database import Model, TimestampsMixin, fields


class User(Model, TimestampsMixin):  # type: ignore[metaclass]
    """Abstract base user model shipped with pylar.

    Marked ``__abstract__ = True`` so it does not create a table on its
    own.  Applications subclass it in ``app/models/user.py`` (generated
    by ``pylar new``) and set ``class Meta: db_table = "users"`` to
    activate the table mapping.

    The model is intentionally minimal: authentication fields only.
    Application-specific fields (roles, profile, preferences) belong
    on the concrete subclass.

    Usage in a project::

        from pylar.auth.user import User as BaseUser

        class User(BaseUser):
            class Meta:
                db_table = "users"

            # Add custom fields here.
            phone = fields.CharField(max_length=20, null=True)
    """

    __abstract__ = True

    name = fields.CharField(max_length=100)
    email = fields.EmailField(unique=True)
    password_hash = fields.CharField(max_length=255)
    is_admin = fields.BooleanField(default=False)

    #: When the user clicks the signed verification link, the
    #: :mod:`pylar.auth.verification` helpers stamp the current time
    #: here. ``None`` means "still unverified" and makes
    #: :class:`RequireVerifiedEmailMiddleware` return 403.
    email_verified_at = fields.DateTimeField(null=True)

    # ---- Authenticatable protocol ----

    @property
    def auth_identifier(self) -> object:
        """Return the value stored in the session to identify this user."""
        return cast(Any, self).id  # PK added by metaclass or subclass

    @property
    def auth_password_hash(self) -> str:
        """Return the stored password hash for verification."""
        return self.password_hash  # type: ignore[return-value]
