"""Email verification + password reset flows (ADR-0009 phase 11c).

The flows share the same shape — build a signed URL, email it, let
the user click, verify the signature, apply the side effect — so they
live in one module under a small set of narrowly-typed helpers. Apps
mount their own controllers and route bindings; the framework only
owns the signing + mutation primitives.

The two middlewares (:class:`RequireVerifiedEmailMiddleware`) guard
downstream routes; they pair naturally with
:class:`pylar.auth.middleware.RequireAuthMiddleware` — authenticate
first, then check verification.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

from pylar.auth.contracts import Authenticatable
from pylar.auth.hashing import PasswordHasher
from pylar.auth.signed import (
    ExpiredSignature,
    InvalidSignature,
    MissingSignature,
    UrlSigner,
)
from pylar.http.middleware import RequestHandler
from pylar.http.request import Request
from pylar.http.response import JsonResponse, Response

#: Default validity window for verification / reset links. Apps can
#: override per-call via the helpers' ``expires_in`` argument.
DEFAULT_VERIFY_TTL = timedelta(hours=24)
DEFAULT_RESET_TTL = timedelta(hours=1)


# ------------------------------------------------------------- signed links


def build_verification_url(
    user: Authenticatable,
    signer: UrlSigner,
    *,
    path: str = "/auth/verify",
    expires_in: timedelta = DEFAULT_VERIFY_TTL,
    extra_params: Mapping[str, str] | None = None,
) -> str:
    """Return the signed ``path?user_id=…&expires=…&signature=…`` URL.

    The URL is relative — apps prepend the public base URL
    (``https://app.example.com``) when embedding it in an email.
    Extra params are folded in before signing so the signature
    covers them too; common additions are a ``redirect=`` query for
    post-verification landing pages.
    """
    params: dict[str, str] = {"user_id": str(user.auth_identifier)}
    if extra_params:
        params.update(extra_params)
    return signer.sign(path, params=params, expires_in=expires_in)


def build_password_reset_url(
    user: Authenticatable,
    signer: UrlSigner,
    *,
    path: str = "/auth/password/reset",
    expires_in: timedelta = DEFAULT_RESET_TTL,
    extra_params: Mapping[str, str] | None = None,
) -> str:
    """Return the signed reset URL — same shape, tighter default TTL."""
    params: dict[str, str] = {"user_id": str(user.auth_identifier)}
    if extra_params:
        params.update(extra_params)
    return signer.sign(path, params=params, expires_in=expires_in)


# ------------------------------------------------------------- verify side


def verify_from_request(
    request: Request,
    signer: UrlSigner,
    *,
    path: str,
) -> dict[str, str]:
    """Validate the incoming request and return the payload params.

    Raises :class:`MissingSignature` / :class:`InvalidSignature` /
    :class:`ExpiredSignature` on the usual failure modes so the caller
    can map each to the right status code.
    """
    query = {k: v for k, v in request.query_params.items()}
    return signer.verify(path, query)


async def mark_email_verified(user: Authenticatable) -> None:
    """Set ``user.email_verified_at = now()`` and persist.

    A no-op if the attribute is already set — idempotent, so a user
    who clicks the link twice does not shift their verified-at
    timestamp forward.
    """
    existing = getattr(user, "email_verified_at", None)
    if existing is not None:
        return
    user.email_verified_at = datetime.now(UTC)  # type: ignore[attr-defined]
    await _save(user)


async def reset_password(
    user: Authenticatable,
    *,
    new_password: str,
    hasher: PasswordHasher,
) -> None:
    """Hash *new_password* with *hasher* and persist on *user*.

    The caller is responsible for rotating the session id after this
    returns (e.g. ``request.session.regenerate()``) so an attacker
    who had a copy of the pre-reset session cannot keep it.
    """
    user.password_hash = hasher.hash(new_password)  # type: ignore[attr-defined]
    await _save(user)


async def _save(user: Authenticatable) -> None:
    """Persist the user via its own query manager — sidesteps the need
    for the caller to know which model class they're holding."""
    query = getattr(type(user), "query", None)
    if query is None:
        return
    await query.save(user)


# ------------------------------------------------------------ middleware


class RequireVerifiedEmailMiddleware:
    """Return 403 when the active user hasn't clicked the verify link.

    Place *after* :class:`RequireAuthMiddleware` so an anonymous
    request fails fast with 401 instead of a misleading 403. Routes
    that don't need verification don't add this middleware.
    """

    async def handle(
        self, request: Request, next_handler: RequestHandler
    ) -> Response:
        from pylar.auth.context import current_user_or_none

        user = current_user_or_none()
        if user is None:
            return JsonResponse(
                content={
                    "error": {
                        "code": "unauthenticated",
                        "message": "Log in to access this route.",
                    }
                },
                status_code=401,
            )
        if getattr(user, "email_verified_at", None) is None:
            return JsonResponse(
                content={
                    "error": {
                        "code": "email_unverified",
                        "message": "Verify your email address before continuing.",
                    }
                },
                status_code=403,
            )
        return await next_handler(request)


# ---------------------------------------------------------- error mapping


def to_response(exc: Exception) -> Response:
    """Map the verification exceptions to the standard error envelope.

    Controllers can simplify their error paths by calling this on the
    exception from :func:`verify_from_request`::

        try:
            payload = verify_from_request(request, signer, path="/auth/verify")
        except (MissingSignature, InvalidSignature, ExpiredSignature) as exc:
            return to_response(exc)
    """
    if isinstance(exc, ExpiredSignature):
        return JsonResponse(
            content={
                "error": {"code": "link_expired", "message": "Link has expired."},
            },
            status_code=410,
        )
    if isinstance(exc, (InvalidSignature, MissingSignature)):
        return JsonResponse(
            content={
                "error": {"code": "link_invalid", "message": "Link is invalid."},
            },
            status_code=400,
        )
    raise TypeError(f"to_response does not handle {type(exc).__name__}")


# --------------------------------------------------------- re-exports


# Anything listed here is part of the module's public API.
__all__ = [
    "DEFAULT_RESET_TTL",
    "DEFAULT_VERIFY_TTL",
    "RequireVerifiedEmailMiddleware",
    "build_password_reset_url",
    "build_verification_url",
    "mark_email_verified",
    "reset_password",
    "to_response",
    "verify_from_request",
]
