# ADR-0009: Authentication Parity — Tokens, Flows, 2FA, Roles

## Status

Accepted. Opens phase 11 of the REVIEW-3 roadmap.

## Context

Pylar ships sessions, Argon2 password hashing, Gate + Policy, and a
`RequireAuthMiddleware`. That's a solid *base* but a long way from
what Laravel (Fortify + Sanctum + Passport + Socialite) or Django
(contrib.auth + django-allauth + django-rest-framework auth) put on
the table for a new project.

The practical list a team expects out of the box in 2026:

* **API tokens** — bearer tokens for single-page apps, mobile clients,
  and service-to-service calls. Laravel's Sanctum is the industry
  reference; revocation, abilities, expiry, last-used tracking.
* **Signed URLs** — for password resets, email verification, invite
  flows, temporary download links.
* **Email verification flow** — user clicks a link, the framework
  flips `email_verified_at`, middleware enforces verification on
  protected routes.
* **Password reset flow** — request → signed URL → throttled reset →
  new session.
* **2FA / TOTP** — RFC 6238 time-based OTP with QR enrolment +
  recovery codes.
* **Roles + Permissions** — role/permission many-to-many on the user,
  `user.has_role("admin")` / `user.can("posts.edit")` on top of the
  existing Gate surface.

OAuth2 server + social login (Socialite) are **out of scope for core**
— they ship as separate `pylar-passport` / `pylar-socialite` packages
using ADR-0005 entry-points, following the same pattern
`pylar-admin` already established (ADR-0004).

## Decision

### 1. API tokens — Sanctum-inspired

```python
class User(Model, Authenticatable):
    ...

# Anywhere:
plain, token = await user.create_token(
    name="Mobile app", abilities=["posts.*"],
    expires_at=datetime.now(UTC) + timedelta(days=30),
)
# return `plain` to the client once; everything stored server-side is
# a SHA-256 hash of `plain`, so a DB leak cannot replay.

# Guarding:
api = router.group(prefix="/api/v1", middleware=[TokenMiddleware])
```

Schema:

```
pylar_api_tokens
  id              bigint pk
  tokenable_type  string      -- fully-qualified class (User, ApiClient)
  tokenable_id    string      -- stringified primary key
  name            string
  token_hash      string idx  -- sha256 hex, indexed for lookup
  abilities       text        -- JSON array; `*` = all
  last_used_at    datetime?
  expires_at      datetime?
  created_at      datetime
```

Wire: ``Authorization: Bearer <plaintext>``. The middleware SHA-256-
hashes, looks up by `token_hash`, enforces `expires_at` + optional
abilities scope, and sets `current_user()` via the Authenticatable
protocol.

**Console commands**

* ``pylar auth:token:list --user user@example.com``
* ``pylar auth:token:create --user ... --name "CI deploy key"``
* ``pylar auth:token:revoke <id>``

### 2. Signed URLs

A small `pylar.auth.signed` module with two helpers:

```python
url = signed.url_for("verify", params={"user_id": 42}, expires_in=timedelta(hours=24))
# http://host/verify?user_id=42&expires=1742400000&signature=<hmac-sha256>

payload = signed.verify(request, expected_route="verify")
# raises InvalidSignature / ExpiredSignature on tamper or expiry
```

Signature is an HMAC-SHA256 of the canonical query (sorted,
URL-encoded) keyed on `APP_KEY` — so rotating the key invalidates
every outstanding link. Reused by the verification and password
reset flows in 11b.

### 3. Email verification flow

Adds `email_verified_at: datetime | None` to the reference
`Authenticatable`. Ships:

* `VerificationController` — `send`, `verify`, `resend` actions.
* `VerifyEmailMailable` — ships a Markdown mailable template.
* `RequireVerifiedEmailMiddleware` — returns 403 for unverified
  users on opt-in routes.

### 4. Password reset flow

* `ForgotPasswordController.send` — accepts email, throttled
  (LoginThrottleMiddleware).
* `ForgotPasswordController.reset` — accepts signed URL + new
  password, hashes it through the bound `PasswordHasher`, bumps
  session id to defeat fixation.

### 5. 2FA TOTP

`pylar.auth.totp`:

* `Totp.generate_secret()` → base32 secret stored on the user row.
* `Totp.provisioning_uri(user, secret)` → ``otpauth://…`` URI for
  QR enrolment (Google Authenticator, 1Password, Bitwarden).
* `Totp.verify(secret, code)` — RFC 6238 with ±1 window tolerance.
* Recovery codes — 8 single-use random codes, stored hashed.

No new dependencies: the RFC 6238 implementation is ~40 lines of
stdlib HMAC-SHA1.

### 6. Roles + Permissions

`pylar.auth.roles`:

* `Role` model (name, label).
* `Permission` model (code, label).
* Pivot tables: `pylar_user_roles`, `pylar_role_permissions`.
* Authenticatable mixin: ``has_role(name)`` / ``has_permission(code)``.
* Gate integration: policies can call
  ``gate.has_permission(user, "posts.edit")`` in addition to the
  existing ability mechanism.

### 7. Deferred

* **OAuth2 server** — separate `pylar-passport` package.
* **Social login** — separate `pylar-socialite` package.
* **WebAuthn / passkeys** — future ADR; too different in shape to
  fold into this one.

## Phasing

* **11a — Signed URLs** (this commit): core primitive reused by
  verify / reset flows.
* **11b — API tokens**: SA model, hasher, middleware, commands,
  migration.
* **11c — Email verification + password reset**: controllers,
  mailables, middleware.
* **11d — 2FA TOTP**: totp core + recovery codes + challenge
  controller.
* **11e — Roles + Permissions**: models, mixin, Gate integration.

Each sub-phase ships green: mypy strict, tests, ADR citation, docs
updated.

## Consequences

* **New core dep**: none. Signed URLs + TOTP use stdlib HMAC;
  API tokens use the existing SA / database layer.
* **Migration**: each sub-phase ships its own Alembic migration for
  the tables it introduces.
* **Backwards compat**: SessionGuard and RequireAuthMiddleware keep
  working unchanged. The new TokenMiddleware / RequireVerifiedEmail
  are additive, opt-in per route group.
* **OAuth2 story** — explicitly out-of-core. Apps that need it today
  can use Authlib behind a custom middleware; the `pylar-passport`
  package will package that pattern later.

## References

* REVIEW-3 section 6 — phase 11 scope.
* ADR-0001 (explicit wiring, no magic).
* ADR-0005 (entry-points — `pylar-passport`, `pylar-socialite` land
  here).
* ADR-0007 (API layer — TokenMiddleware is the auth slot the ADR
  reserved).
