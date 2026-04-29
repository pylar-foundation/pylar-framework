"""Authentication and authorization layer for pylar.

Note: ``User`` and ``AuthServiceProvider`` are importable from
``pylar.auth.user`` and ``pylar.auth.provider`` respectively.
They are not re-exported here to avoid a circular import:
``auth → user → database → http → routing → auth``.
"""

from pylar.auth.config import AuthConfig
from pylar.auth.context import authenticate_as, current_user, current_user_or_none
from pylar.auth.contracts import Authenticatable, Guard
from pylar.auth.csrf import CsrfMiddleware
from pylar.auth.exceptions import (
    AuthenticationError,
    AuthError,
    AuthorizationError,
    NoCurrentUserError,
)
from pylar.auth.gate import AbilityCallback, Gate
from pylar.auth.hashing import (
    Argon2PasswordHasher,
    PasswordHasher,
    Pbkdf2PasswordHasher,
)
from pylar.auth.middleware import (
    AuthMiddleware,
    AuthorizeMiddleware,
    LoginThrottleMiddleware,
    RequireAuthMiddleware,
    authorize,
)
from pylar.auth.policy import Policy
from pylar.auth.roles import (
    Permission,
    Role,
    RolePermission,
    UserRole,
    assign_role,
    grant_permission,
    has_permission,
    has_role,
    revoke_permission,
    revoke_role,
    user_permissions,
    user_roles,
)
from pylar.auth.session_guard import SessionGuard, UserResolver
from pylar.auth.signed import (
    ExpiredSignature,
    InvalidSignature,
    MissingSignature,
    UrlSigner,
)
from pylar.auth.tokens import (
    ApiToken,
    TokenMiddleware,
    create_api_token,
    generate_token,
    hash_token,
)
from pylar.auth.totp import (
    generate_recovery_codes,
    generate_secret,
    hash_recovery_code,
    provisioning_uri,
    verify_recovery_code,
)
from pylar.auth.verification import (
    RequireVerifiedEmailMiddleware,
    build_password_reset_url,
    build_verification_url,
    mark_email_verified,
    reset_password,
    verify_from_request,
)

# Lazy imports to break circular dependency.
# Use: from pylar.auth.user import User
# Use: from pylar.auth.provider import AuthServiceProvider

__all__ = [
    "AbilityCallback",
    "ApiToken",
    "Argon2PasswordHasher",
    "AuthConfig",
    "AuthError",
    "AuthMiddleware",
    "Authenticatable",
    "AuthenticationError",
    "AuthorizationError",
    "AuthorizeMiddleware",
    "CsrfMiddleware",
    "ExpiredSignature",
    "Gate",
    "Guard",
    "InvalidSignature",
    "LoginThrottleMiddleware",
    "MissingSignature",
    "NoCurrentUserError",
    "PasswordHasher",
    "Pbkdf2PasswordHasher",
    "Permission",
    "Policy",
    "RequireAuthMiddleware",
    "RequireVerifiedEmailMiddleware",
    "Role",
    "RolePermission",
    "SessionGuard",
    "TokenMiddleware",
    "UrlSigner",
    "UserResolver",
    "UserRole",
    "assign_role",
    "authenticate_as",
    "authorize",
    "build_password_reset_url",
    "build_verification_url",
    "create_api_token",
    "current_user",
    "current_user_or_none",
    "generate_recovery_codes",
    "generate_secret",
    "generate_token",
    "grant_permission",
    "has_permission",
    "has_role",
    "hash_recovery_code",
    "hash_token",
    "mark_email_verified",
    "provisioning_uri",
    "reset_password",
    "revoke_permission",
    "revoke_role",
    "user_permissions",
    "user_roles",
    "verify_from_request",
    "verify_recovery_code",
]


def __getattr__(name: str) -> object:
    """Lazy-load User and AuthServiceProvider to avoid circular imports."""
    if name == "User":
        from pylar.auth.user import User

        return User
    if name == "AuthServiceProvider":
        from pylar.auth.provider import AuthServiceProvider

        return AuthServiceProvider
    raise AttributeError(f"module 'pylar.auth' has no attribute {name!r}")
