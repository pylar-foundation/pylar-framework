# ADR-0013: WebAuthn and Passkeys

## Status

Proposed. Follow-up to ADR-0009 (Authentication Parity), which
deferred WebAuthn explicitly: TOTP shipped as the 2FA primitive but
passkeys "require a separate ADR — too different from TOTP to bolt
on". This ADR is that follow-up. Target phase: 15 (post-1.0 minor
release).

## Context

Three shifts in the authentication landscape since ADR-0009
shipped:

1. **Passkeys crossed mainstream adoption.** Apple, Google, Microsoft,
   GitHub, GitLab, Amazon, PayPal, and eBay default to WebAuthn for
   new accounts. Password managers (1Password, Bitwarden, Dashlane)
   treat passkeys as first-class. Consumer expectation has moved from
   "nice-to-have optional" to "we expected you to support this".
2. **TOTP phishability is now material.** TOTP codes can be proxied
   through evilginx-style reverse proxies; WebAuthn cannot, because
   the browser binds every assertion to the exact origin it was
   issued for. For any app that cares about takeover resistance,
   WebAuthn is strictly stronger.
3. **`py_webauthn` stabilised.** The canonical Python library
   (maintained by the Duo security team originally, community now)
   reached 2.x with a clean typed API for the two ceremonies we need
   (registration + authentication). No more hand-rolled CBOR / COSE
   plumbing.

Pylar's current 2FA surface is TOTP only. The longer we wait, the
more apps ship `pylar-webauthn` third-party packages that each
re-invent the credential schema, and the harder a first-party
consolidation becomes. Better to land the core primitive now and let
UI flavour (enrolment wizard, backup-code fallback UX) live in
`pylar-admin` or user code.

## Decision

### 1. Library choice: `py_webauthn`

New optional extra:

```toml
[project.optional-dependencies]
webauthn = ["webauthn>=2.0,<3"]
```

`webauthn>=2.0` is actively maintained, pure-Python, Apache-2.0, and
provides exactly the two primitives we need:

* `generate_registration_options()` / `verify_registration_response()`
* `generate_authentication_options()` / `verify_authentication_response()`

Rejected alternatives:

* **`python-fido2`** (Yubico): lower-level, great for YubiKey native
  integrations, but forces us to re-implement the high-level
  ceremony helpers. We'd write the same glue `py_webauthn` already
  ships.
* **Hand-roll on top of `cryptography`**: technically possible,
  maintenance-heavy, no wins.

### 2. Data model

A single credential table with the polymorphic tokenable pattern
already established by `ApiToken` in ADR-0009:

```python
class WebauthnCredential(Model):
    class Meta:
        db_table = "pylar_webauthn_credentials"

    tokenable_type: Mapped[str]          # "app.models.user.User"
    tokenable_id:   Mapped[str]          # stringified primary key
    credential_id:  Mapped[bytes]        # unique, base64url on the wire
    public_key:     Mapped[bytes]        # COSE-encoded public key
    sign_count:     Mapped[int]          # monotonic counter
    aaguid:         Mapped[str | None]   # authenticator model hint
    transports:     Mapped[list[str]]    # ["usb","nfc","internal",...]
    backup_eligible: Mapped[bool]        # BE flag — syncable passkey?
    backup_state:   Mapped[bool]         # BS flag — currently backed up?
    nickname:       Mapped[str | None]   # user-chosen label
    last_used_at:   Mapped[datetime | None]
    created_at:     Mapped[datetime]
```

SQL indexes: unique on `credential_id`, composite index on
`(tokenable_type, tokenable_id)` for listing a user's passkeys.

One Alembic migration ships with the module; nothing in the runtime
creates the table lazily (same as every other `pylar_*` table).

### 3. Configuration

A new `WebauthnConfig` bound via `config/auth.py`:

```python
class WebauthnConfig(BaseConfig):
    rp_id: str              # "example.com" — the security boundary
    rp_name: str            # "Example"    — display name in UI prompts
    origin: str | None = None  # defaults to request-derived origin
    user_verification: Literal["required", "preferred", "discouraged"] = "preferred"
    attestation: Literal["none", "direct", "indirect"] = "none"
    challenge_ttl_seconds: int = 300
```

The `rp_id` is load-bearing: WebAuthn binds credentials to the
exact RP ID that registered them, so moving a deployment from
`app.example.com` to `example.com` invalidates every existing
passkey. Operators set this consciously at boot, not dynamically per
request.

Attestation defaults to `"none"` — that matches GitHub / Google /
Microsoft and avoids the operational overhead of FIDO MDS
integration. Apps that need supply-chain attestation (regulated
industries) flip to `"direct"` and plug in their own verifier.

### 4. Ceremony surface: `WebauthnServer`

One service class, four async methods, no request coupling:

```python
class WebauthnServer:
    async def make_registration_options(
        self, user: Authenticatable, *, exclude_existing: bool = True,
    ) -> RegistrationOptions: ...

    async def verify_registration(
        self, user: Authenticatable, response: dict, *, nickname: str | None = None,
    ) -> WebauthnCredential: ...

    async def make_authentication_options(
        self, user: Authenticatable | None = None,
    ) -> AuthenticationOptions: ...

    async def verify_authentication(
        self, response: dict,
    ) -> tuple[Authenticatable, WebauthnCredential]: ...
```

`make_*_options` generates a server-side random challenge, stores
it in the ambient `Session` under a module-reserved key, and
returns a Pydantic model ready to JSON-serialise to the client.
`verify_*` pulls the challenge back, delegates to `py_webauthn`,
updates `sign_count` + `last_used_at`, and raises
`WebauthnVerificationError` on any failure (tampered response,
expired challenge, origin mismatch, unknown credential, sign-count
regression).

The challenge TTL mirrors the library default of 5 minutes. A
regression in `sign_count` is treated as a cloned-credential signal
and logged but not auto-rejected — the decision to force a
re-enrolment is left to application policy (same stance Webauthn
guides recommend).

### 5. Route contract

The framework does not mount opinionated routes — the same choice
ADR-0009 made for the verification + reset flows. Apps wire their
own controllers. Typical shape:

```python
# app/controllers/passkeys.py
class PasskeyController:
    def __init__(self, webauthn: WebauthnServer): ...

    async def register_begin(self, request: Request) -> JsonResponse:
        user = current_user()
        opts = await self.webauthn.make_registration_options(user)
        return json(opts.model_dump())

    async def register_finish(self, request: Request) -> JsonResponse:
        user = current_user()
        body = await request.json()
        cred = await self.webauthn.verify_registration(
            user, body, nickname=body.get("nickname"),
        )
        return json({"id": cred.id, "nickname": cred.nickname})

    async def login_begin(self, request: Request) -> JsonResponse:
        # Discoverable-credential flow — no user hint.
        opts = await self.webauthn.make_authentication_options()
        return json(opts.model_dump())

    async def login_finish(self, request: Request, guard: Guard) -> JsonResponse:
        body = await request.json()
        user, _cred = await self.webauthn.verify_authentication(body)
        await guard.login(user)
        return json({"ok": True})
```

### 6. Integration with the existing 2FA pipeline

`pylar.auth.twofactor` (from ADR-0009) exposes a `Required2FAMiddleware`
that checks whether the session has passed a second factor. WebAuthn
plugs in as a *second second factor*: any enrolled WebAuthn credential
or any confirmed TOTP secret satisfies the check. This is the Laravel
Fortify posture — let users choose their factor rather than force a
migration.

Concretely, the middleware's "is 2FA complete?" predicate becomes:

```python
async def _has_second_factor(user: Authenticatable) -> bool:
    return (
        session.get("twofactor.totp_confirmed_at") is not None
        or session.get("webauthn.assertion_at") is not None
    )
```

`verify_authentication` stamps `webauthn.assertion_at` on the
ambient session automatically — no app glue required.

### 7. Console commands

```bash
pylar auth:webauthn:list --user user@example.com
pylar auth:webauthn:revoke <credential-id>
pylar auth:webauthn:prune --days 180   # drop credentials unused for N days
```

No `register` command — registration requires a real browser.

### 8. Phasing

| Phase | Scope | Ship criterion |
|---|---|---|
| **15a** | `WebauthnServer`, model, config, migration, `py_webauthn` extra, 2FA integration | Green tests for both ceremonies; demo route in the blog example |
| **15b** | Passwordless primary flow (`SessionGuard.login_with_webauthn()`), discoverable-credential support, `login_begin`/`finish` helpers | Blog example supports passkey-only login |
| **15c** | Console commands, `pylar-admin` UI for listing + revoking credentials | Admin users can manage their passkeys |
| **15d** | Optional FIDO MDS attestation verifier, `attestation="direct"` path | On request from an operator who needs it |

Phases 15a + 15b land together in the same release; 15c + 15d are
separable and may skip into later minors if no demand appears.

## Consequences

### Positive

* Phishing-resistant 2FA available out of the box, matching the
  Laravel Fortify / Passport + filament-webauthn combined surface.
* Path to passwordless login without a new framework dependency
  (password hashers, sessions, guards all stay as-is).
* Single credential model covers both 2FA and passwordless — apps
  don't have to run two tables for two ceremonies.

### Negative

* New optional dependency (`webauthn>=2.0`) with a small transitive
  graph (`cryptography`, `pyOpenSSL`, `cbor2`). Apps that never opt
  in are unaffected.
* The `rp_id` coupling is tight — moving domains invalidates every
  credential. This is a WebAuthn spec property, not a pylar choice,
  and must be called out prominently in the user-facing docs.
* Sign-count regression policy is "log and continue" by default.
  Applications in high-assurance contexts may want
  "log and force re-enrolment" — configurable in a follow-up if
  needed.

### Out of scope

* **Cross-device credential sync.** Handled entirely by the OS /
  browser / password manager — the server sees the synced credential
  as just another credential.
* **FIDO MDS (Metadata Service) integration.** Enterprise-only
  concern; ships in phase 15d behind a config flag.
* **Conditional UI autofill on the login form.** A client-side JS
  concern; the server-side `make_authentication_options(user=None)`
  already supports the flow.
* **WebAuthn signed extensions** (`credBlob`, `largeBlob`,
  `credProps`). Not commonly used; revisit if demand appears.
* **Enterprise attestation conveyance** (`enterprise` policy). Out
  of core; users who need it can pass `attestation="direct"` and
  write their own verifier.

## References

* [W3C WebAuthn Level 3](https://www.w3.org/TR/webauthn-3/) — the
  authoritative spec.
* [py_webauthn](https://github.com/duo-labs/py_webauthn) — the
  library this ADR picks.
* ADR-0009 — the auth-parity work this ADR extends. Specifically
  sections 1 (API tokens, for the polymorphic tokenable pattern)
  and 5 (TOTP 2FA, for the integration point).
* ADR-0012 — the encryption primitive that already manages `APP_KEY`;
  WebAuthn does not need additional keying material.
