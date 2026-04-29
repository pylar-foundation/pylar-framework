"""Configuration for the session middleware."""

from __future__ import annotations

import logging
import warnings
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SameSite = Literal["lax", "strict", "none"]

_logger = logging.getLogger("pylar.session")

#: Known-weak default secrets that must not survive to production.
_WEAK_SECRETS = frozenset({
    "change-me",
    "change-me-in-production",
    "demo-secret-do-not-ship",
    "secret",
    "password",
    "",
})


class SessionConfig(BaseModel):
    """Tuning knobs for :class:`SessionMiddleware`.

    *secret_key* signs every session cookie with HMAC-SHA-256 so a
    forged cookie cannot map onto a valid session. The other fields
    mirror the standard cookie attributes; the defaults match the
    advice from current OWASP session-management guidance — HTTP-only,
    SameSite=Lax, two-week lifetime.

    Boot-time validation warns on known-weak secrets and on
    ``cookie_secure=False`` so misconfigurations are visible at
    startup rather than in a post-incident review.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    secret_key: str
    cookie_name: str = "pylar_session_id"
    cookie_path: str = "/"
    cookie_domain: str | None = None
    cookie_secure: bool = False
    cookie_http_only: bool = True
    cookie_same_site: SameSite = "lax"
    lifetime_seconds: int = Field(default=14 * 24 * 60 * 60, ge=1)

    @model_validator(mode="after")
    def _validate_security(self) -> SessionConfig:
        if self.secret_key in _WEAK_SECRETS:
            warnings.warn(
                f"SessionConfig.secret_key is a known-weak default "
                f"({self.secret_key!r}). Generate a strong random key "
                f"for production.",
                UserWarning,
                stacklevel=2,
            )
        if len(self.secret_key) < 16:
            warnings.warn(
                f"SessionConfig.secret_key is only {len(self.secret_key)} "
                f"chars — OWASP recommends at least 32 bytes for HMAC-SHA256.",
                UserWarning,
                stacklevel=2,
            )
        if not self.cookie_secure:
            _logger.info(
                "SessionConfig.cookie_secure=False — session cookie will "
                "be sent over plaintext HTTP. Set cookie_secure=True in "
                "production behind HTTPS."
            )
        return self
