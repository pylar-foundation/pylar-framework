# auth/ — backlog

## ~~Argon2PasswordHasher~~ ✓
## ~~RequireAuthMiddleware~~ ✓
## ~~CsrfMiddleware~~ ✓
## ~~SessionGuard~~ ✓
## ~~Signed URLs~~ ✓ (ADR-0009 phase 11a)

`UrlSigner` — HMAC-SHA256 keyed on APP_KEY, optional expiry.

## ~~API tokens~~ ✓ (ADR-0009 phase 11b)

Sanctum-style: `ApiToken` model, `TokenMiddleware`, SHA-256 hashed
storage, abilities with wildcard/prefix matching, expiry, last-used.

## ~~Email verification + password reset~~ ✓ (ADR-0009 phase 11c)

`build_verification_url`, `build_password_reset_url`,
`mark_email_verified`, `reset_password`,
`RequireVerifiedEmailMiddleware`.

## ~~2FA TOTP~~ ✓ (ADR-0009 phase 11d)

RFC 6238 stdlib implementation, `generate_secret`, `provisioning_uri`,
`verify` (±1 window), recovery codes (hashed, single-use).

## ~~Roles + permissions~~ ✓ (ADR-0009 phase 11e)

`Role`, `Permission`, `UserRole`, `RolePermission` models.
`assign_role`, `has_role`, `has_permission`, `user_permissions`.
Wildcard codes `posts.*`.

## Still on the wishlist

### `@authorize` decorator

Sugar for route-level `gate.authorize(user, ability, target)`.

### OAuth2 server

Deferred to `pylar-passport` package (ADR-0005 entry-points).

### Social login

Deferred to `pylar-socialite` package.

### WebAuthn / passkeys

Future ADR — shape is too different from TOTP to fold in.

### Permission groups / team scoping

Tenancy-aware permission assignment — scoped roles per tenant.
Depends on `pylar.tenancy` Tier B/C.
