"""API token authentication — Sanctum-style (ADR-0009 phase 11b).

Three public surfaces:

* :class:`ApiToken` — the SA-mapped row for an issued token. Stored
  values are SHA-256 hashes of the plaintext, so a database leak does
  not let an attacker replay live tokens.
* :func:`create_api_token` — mint a token for an ``Authenticatable``.
  Returns ``(plaintext, ApiToken)``; the plaintext must be handed to
  the client exactly once and then forgotten on the server.
* :class:`TokenMiddleware` — reads ``Authorization: Bearer …``, looks
  the hash up, enforces ``expires_at`` and (optionally) ``abilities``,
  and pins the authenticated user for the rest of the request via
  :func:`pylar.auth.authenticate_as`.

The design mirrors Laravel's Sanctum. ``tokenable_type`` +
``tokenable_id`` are the same denormalised polymorphic shape — one
``pylar_api_tokens`` table supports tokens on user models, on API
client rows, or on anything else that satisfies the
:class:`Authenticatable` protocol.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from pylar.auth.context import authenticate_as
from pylar.auth.contracts import Authenticatable
from pylar.database import Model, fields

#: Length of the raw secret (URL-safe base64). 32 bytes → ~43 chars.
#: Prefix ``pylat_`` (pylar + "api token") for log filtering.
_TOKEN_PREFIX = "pylat_"
_TOKEN_BYTES = 32


class ApiToken(Model):  # type: ignore[metaclass]
    """SA-mapped row for an issued API token.

    Applications typically do *not* touch this class directly — use
    :func:`create_api_token` to mint tokens and the
    :class:`TokenMiddleware` to consume them. The class is exposed so
    the user model's migrations pick up the table.
    """

    class Meta:
        db_table = "pylar_api_tokens"

    tokenable_type = fields.CharField(max_length=255, index=True)
    tokenable_id = fields.CharField(max_length=64, index=True)
    name = fields.CharField(max_length=120)
    token_hash = fields.CharField(max_length=64, unique=True, index=True)
    abilities = fields.TextField(default="[]")  # JSON array of strings
    last_used_at = fields.DateTimeField(null=True)
    expires_at = fields.DateTimeField(null=True, index=True)
    created_at = fields.DateTimeField(auto_now_add=True)

    # ---------------------------------------------------------- helpers

    @property
    def ability_list(self) -> list[str]:
        """Parsed ``abilities`` JSON; empty list means "all abilities"."""
        raw = getattr(self, "abilities", None) or "[]"
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return []
        if not isinstance(parsed, list):
            return []
        return [str(a) for a in parsed]

    def can(self, ability: str) -> bool:
        """Does this token carry *ability* (directly or via ``*`` wildcard)?

        An empty list is treated as "all abilities granted" — matches
        Sanctum's default when no abilities are passed to ``createToken``.
        Pass ``abilities=["*"]`` explicitly for the same effect, or list
        specific abilities to scope the token down.
        """
        abilities = self.ability_list
        if not abilities or "*" in abilities:
            return True
        if ability in abilities:
            return True
        # Prefix match: ``posts.*`` grants ``posts.edit``.
        for granted in abilities:
            if granted.endswith(".*") and ability.startswith(granted[:-1]):
                return True
        return False

    def is_expired(self, *, now: datetime | None = None) -> bool:
        expires = getattr(self, "expires_at", None)
        if expires is None:
            return False
        # SQLite round-trips datetimes as naive; normalise to UTC so
        # comparisons work regardless of the backend.
        if isinstance(expires, datetime) and expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        moment = now or datetime.now(UTC)
        return bool(expires <= moment)


# --------------------------------------------------------- hashing helpers


def hash_token(plaintext: str) -> str:
    """Return the hex SHA-256 digest stored in :attr:`ApiToken.token_hash`.

    SHA-256 rather than Argon2: the plaintext is 32 bytes of CSPRNG
    output, so adaptive password hashing buys nothing — it would only
    slow the per-request middleware down without adding security.
    """
    return hashlib.sha256(plaintext.encode()).hexdigest()


def generate_token() -> str:
    """Mint a fresh plaintext token with the ``pylat_`` prefix."""
    return _TOKEN_PREFIX + secrets.token_urlsafe(_TOKEN_BYTES)


# ---------------------------------------------------------- minting


async def create_api_token(
    user: Authenticatable,
    *,
    name: str,
    abilities: Sequence[str] | None = None,
    expires_at: datetime | None = None,
    expires_in: timedelta | None = None,
) -> tuple[str, ApiToken]:
    """Mint a token for *user* and persist the hashed row.

    Returns ``(plaintext, ApiToken)``. The plaintext is the only thing
    the caller can hand back to the client — the server keeps the hash.
    Pass exactly one of *expires_at* / *expires_in* (or neither for a
    non-expiring token).
    """
    if expires_at is not None and expires_in is not None:
        raise ValueError("pass only one of expires_at / expires_in")
    if expires_in is not None:
        expires_at = datetime.now(UTC) + expires_in

    plaintext = generate_token()
    user_cls = type(user)
    token = ApiToken(
        tokenable_type=f"{user_cls.__module__}.{user_cls.__qualname__}",
        tokenable_id=str(user.auth_identifier),
        name=name,
        token_hash=hash_token(plaintext),
        abilities=json.dumps(list(abilities) if abilities else []),
        expires_at=expires_at,
    )
    await ApiToken.query.save(token)
    return plaintext, token


# ---------------------------------------------------------- middleware


class TokenMiddleware:
    """HTTP middleware that authenticates via ``Authorization: Bearer``.

    Attach to an API route group. On a request with a valid bearer
    header the middleware:

    1. Resolves the token row by SHA-256 hash.
    2. Rejects expired tokens with 401.
    3. Looks up the tokenable (the user) via its model's query surface.
    4. Pins the user on the current scope with
       :func:`authenticate_as` and bumps ``last_used_at``.

    A request without a bearer header passes through silently — the
    downstream :class:`RequireAuthMiddleware` is responsible for
    deciding whether anonymous access is allowed.

    Optionally constrain routes to a specific ability by subclassing::

        class EditPostsMiddleware(TokenMiddleware):
            required_ability = "posts.edit"
    """

    required_ability: str | None = None

    async def handle(self, request: Any, next_handler: Any) -> Any:
        auth = request.headers.get("authorization", "")
        if not auth.lower().startswith("bearer "):
            return await next_handler(request)

        plaintext = auth.split(" ", 1)[1].strip()
        if not plaintext:
            return await next_handler(request)

        token = await _find_token(plaintext)
        if token is None or token.is_expired():
            return _unauthorized("invalid_or_expired_token")

        if self.required_ability and not token.can(self.required_ability):
            return _unauthorized("token_missing_ability")

        user = await _resolve_tokenable(token)
        if user is None:
            return _unauthorized("tokenable_missing")

        # Stamp last_used_at through an UPDATE rather than a full save
        # so the per-request write stays as cheap as possible.
        await _touch_last_used(token)

        request.scope["api_token"] = token
        with authenticate_as(user):
            return await next_handler(request)


# ----------------------------------------------------------- internals


async def _find_token(plaintext: str) -> ApiToken | None:
    token_hash = hash_token(plaintext)
    predicate = ApiToken.token_hash == token_hash  # type: ignore[comparison-overlap]
    return await ApiToken.query.where(predicate).first()  # type: ignore[arg-type]


async def _resolve_tokenable(token: ApiToken) -> Authenticatable | None:
    import importlib

    qualified = str(getattr(token, "tokenable_type", ""))
    raw_id = str(getattr(token, "tokenable_id", ""))
    module_path, _, class_name = qualified.rpartition(".")
    if not module_path or not class_name:
        return None
    try:
        module = importlib.import_module(module_path)
    except ImportError:
        return None
    cls = getattr(module, class_name, None)
    if cls is None:
        return None
    try:
        user = await cls.query.where(cls.id == _coerce_id(raw_id)).first()
    except Exception:
        return None
    return user  # type: ignore[no-any-return]


def _coerce_id(raw: str) -> object:
    """Best-effort coerce stringified primary key back to int or uuid."""
    try:
        return int(raw)
    except ValueError:
        return raw


async def _touch_last_used(token: ApiToken) -> None:
    token.last_used_at = datetime.now(UTC)  # type: ignore[assignment]
    try:
        await ApiToken.query.save(token)
    except Exception:
        # Best-effort — a transient write failure shouldn't reject an
        # otherwise valid request.
        pass


def _unauthorized(reason: str) -> Any:
    from pylar.http.response import JsonResponse

    return JsonResponse(
        content={"error": {"code": "unauthenticated", "message": reason}},
        status_code=401,
    )
