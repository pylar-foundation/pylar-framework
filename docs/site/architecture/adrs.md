# Architecture Decision Records

Pylar uses ADRs to document every significant architectural choice. Each ADR
is a Markdown file in [`docs/adr/`](https://github.com/fso/pylar/tree/main/docs/adr)
that captures the context, the decision, and the consequences.

!!! tip "Read the Constitution first"
    For the **distilled rules** that every ADR below builds on —
    strict typing, async I/O, no `**kwargs` in public APIs, the
    migration-stub naming contract, and so on — see the
    [Constitution](https://github.com/fso/pylar/blob/main/pylar-framework/docs/CONSTITUTION.md).
    It's the short index; the ADRs are the detailed reasoning.

## The ADR process

1. **Before proposing an architectural change**, read the existing ADRs. They
   are the source of truth for why the codebase is shaped the way it is.
2. When a new decision is needed, create a new file
   `docs/adr/NNNN-short-title.md` with sections: Status, Context, Decision,
   Consequences.
3. ADRs are **immutable once accepted**. If a decision is reversed, write a
   new ADR that supersedes the old one rather than editing it.

## Current ADRs

### ADR-0001: Foundation Principles

:material-file-document: `docs/adr/0001-foundation-principles.md`

**Status:** Accepted

Establishes the core principles that every later decision is measured against.

**Key decisions:**

- **Protocol-first design.** Every subsystem is described by `typing.Protocol`
  or `ABC`. Business code never imports concrete infrastructure classes.
- **Async-first.** Every I/O contract is `async def`. Sync variants exist only
  where async makes no sense (CLI bootstrap, migrations).
- **No `**kwargs` in public APIs.** Parameters are explicit and typed. The
  container refuses to resolve constructors that lack type hints.
- **Explicit over implicit.** No autodiscovery by string. Service Providers
  are listed by import in `config/app.py`.
- **Strict mypy + ruff.** `disallow_untyped_defs`, `disallow_any_generics`,
  `strict_optional`. CI blocks regressions.
- **One way to do one thing.** No parallel mechanisms for the same use case.

**What pylar takes from Laravel:** IoC Container, routing with groups,
Eloquent-style models (on SQLAlchemy), Form Requests as DTOs, Queues/Jobs,
Policies/Gates, Mailables, Notifications, Scheduler, CLI generators,
Broadcasting, Service Providers.

**What pylar takes from Django:** Admin panel (deferred), auto-migrations via
Alembic, QuerySet API with F/Q expressions, i18n.

**What pylar explicitly avoids:** Facades, `**kwargs`, magical `__getattr__`,
monolithic `settings.py`, string references to classes.

---

### ADR-0002: Project Structure

:material-file-document: `docs/adr/0002-project-structure.md`

**Status:** Accepted

Defines the framework package layout and the user project layout that pylar
generates.

**Key decisions:**

- `foundation/` is the bottom of the stack -- it must not import from any
  other pylar module at load time.
- `http/` re-exports Starlette types so user code never imports Starlette
  directly.
- `routing/` depends on `http/` and `foundation/`, never the reverse.
- `support/` contains only typed generic data structures (`Collection[T]`,
  `Pipeline[T]`). It is not a junk drawer.
- The application lifecycle follows a strict sequence: config loading,
  provider `register` (bindings only), provider `boot` (side effects),
  kernel run, provider `shutdown` in reverse order.

---

### ADR-0003: Technology Stack

:material-file-document: `docs/adr/0003-tech-stack.md`

**Status:** Accepted

Locks the third-party library choices that shape every layer above them.

| Concern        | Choice                   | Rationale                                        |
|----------------|--------------------------|--------------------------------------------------|
| ORM            | SQLAlchemy 2.0 (async)   | Exposed, not hidden -- users can drop to raw SA  |
| HTTP core      | Starlette (>= 0.40)     | Thin typed wrapper, no custom ASGI plumbing      |
| DTOs           | Pydantic v2              | `BaseConfig`, `RequestDTO`, job payloads         |
| Templating     | Jinja2 (>= 3.1)         | Mature, fast, type stubs available               |
| CLI            | Custom over `argparse`   | Full control over type signatures                |
| Min Python     | 3.12                     | Required for PEP 695 generics                    |
| Lint / type    | ruff + mypy strict       | CI blocks regressions                            |
| Migrations     | Alembic (autogenerate)   | Wrapped inside `database/`                       |
| Model events   | Laravel-style observers  | Django Signals explicitly rejected (too implicit) |
| Admin panel    | Postponed                | Leaning HTMX server-rendered when revisited      |

**Consequences:** Pylar inherits Starlette's strengths and limitations.
SQLAlchemy is an exposed foundation, not a hidden detail. The custom CLI
layer is more maintenance but preserves end-to-end typing. Python 3.12 floor
blocks older systems but is non-negotiable for the generics syntax.

---

### ADR-0004: Admin Panel

:material-file-document: `docs/adr/0004-admin-panel.md`

**Status:** Accepted.

Splits the admin into a separate `pylar-admin` package that ships as an
entry-point plugin. Keeps the core framework slim and lets the admin
evolve on its own release cadence — see ADR-0005 for the autodiscovery
mechanism it relies on.

---

### ADR-0005: Package Autodiscovery via Entry Points

:material-file-document: `docs/adr/0005-package-autodiscovery.md`

**Status:** Accepted. Supersedes ADR-0001's "no autodiscovery" clause for
third-party packages (user project providers remain explicit).

Third-party plugins register `ServiceProvider`s under the `pylar.providers`
entry-points group. `AppConfig.autodiscover=True` wires them in at bootstrap
automatically; the `package:list` command introspects what is present. User
project providers stay explicit in `config/app.py`.

---

### ADR-0006: Named Queues, Priorities, Per-Queue Config, Supervised Workers

:material-file-document: `docs/adr/0006-multi-queue-priorities-and-supervision.md`

**Status:** Accepted, fully shipped (three phases in production).

Replaces the single-queue model with named queues (`high`, `default`, `low`
by convention, open-ended in practice), priority-ordered `pop`, per-queue
`QueueConfig` (tries / timeout / backoff / min_workers / max_workers /
scale_threshold / scale_cooldown_seconds), and a `QueueSupervisor`
autoscaler. `queue:work --queue=high,default,low` and `queue:supervisor`
are the two operator entry points.

Jobs declare a default queue via `queue: ClassVar[str]`; dispatch-time
`queue="…"` beats the class default. Policy layering: Job class attribute
beats QueueConfig beats framework defaults — operators tune whole queues
without editing job code, job authors pin behaviour when it matters.

---

### ADR-0007: API Layer and OpenAPI Generation

:material-file-document: `docs/adr/0007-api-layer-and-openapi.md`

**Status:** Accepted, fully shipped (three sub-phases).

Defines the REST/JSON surface of a pylar application: pydantic BaseModel
doubles as the resource abstraction (no parallel serializer hierarchy),
`Page[T]` is the pagination envelope, `ApiError` + `ApiErrorMiddleware`
produce the stable error shape, and the OpenAPI 3.1 generator walks the
router at boot to emit a spec driven entirely by type hints.

`ApiServiceProvider` mounts three endpoints: `GET /openapi.json` (the
cached spec), `GET /docs` (Swagger UI via CDN), `GET /redoc` (ReDoc via
CDN). The `pylar api:docs` command dumps the spec for CI consumers.
Controllers that return `BaseModel`, `list[BaseModel]`, or `Page[T]` are
auto-serialised by the routing compiler — hand-written `json(...)` calls
remain supported for non-JSON responses.

URL-prefix versioning (`/api/v1/…`) is the recommended approach. API
tokens, OAuth, and 2FA are deferred to ADR-0009 (phase 11).

---

### ADR-0008: Observability

:material-file-document: `docs/adr/0008-observability.md`

**Status:** Accepted, fully shipped across four phases.

Defines pylar's observability story: core foundations ship
dependency-free; OpenTelemetry / Prometheus / Sentry are opt-in
extras. Core gives `pylar about` (resolved config dump), `pylar
doctor` (health probes, non-zero exit on failure), and
`install_json_logging()` (structured JSON logs correlated with the
existing `RequestIdMiddleware`).

Opt-in integrations:

* `pylar[otel]` — `OtelServiceProvider` + `OtelJobMiddleware` +
  env-driven OTLP exporter.
* `pylar[prometheus]` — `/metrics` endpoint + HTTP and queue
  collectors following OpenTelemetry semantic conventions.
* `pylar[sentry]` — auto-init from env, `SentryHttpMiddleware` +
  `SentryJobMiddleware` tagging the scope with the correlation id.

---

### ADR-0009: Authentication Parity

:material-file-document: `docs/adr/0009-auth-parity.md`

**Status:** Accepted, fully shipped across five phases.

Closes the auth-parity gap identified in the 0.3.x architecture review: signed URLs,
Sanctum-style API tokens, email verification + password reset flows,
TOTP 2FA with recovery codes, and roles + permissions. All
stdlib-only — zero new runtime dependencies.

* **Signed URLs** (`UrlSigner`): HMAC-SHA256 over the canonical
  query, keyed on `APP_KEY`. Primitive for verify / reset / invite
  flows.
* **API tokens** (`ApiToken`, `TokenMiddleware`): Sanctum-inspired
  bearer tokens with polymorphic tokenable, SHA-256-hashed storage,
  abilities with wildcard support, expiry, last-used tracking.
* **Verification + reset flows**: narrow helpers (`build_*_url`,
  `verify_from_request`, `mark_email_verified`, `reset_password`)
  + `RequireVerifiedEmailMiddleware`. Apps mount their own
  controllers.
* **2FA TOTP** (`pylar.auth.totp`): stdlib RFC 6238 implementation
  with QR provisioning URI, ±1-window drift tolerance, pinned
  against the RFC reference vectors. Recovery codes store as
  SHA-256 hashes, consume-on-match.
* **Roles + Permissions** (`pylar.auth.roles`): four SA-mapped
  tables + async helpers (`assign_role`, `has_permission`,
  `user_permissions`). Wildcard permission codes (`posts.*`)
  mirror the ability model on API tokens.

OAuth2 server and social login stay out of core — slotted for
`pylar-passport` / `pylar-socialite` separate packages via
ADR-0005 entry points.

---

### ADR-0010: LTS Cadence and SemVer Contract

:material-file-document: `docs/adr/0010-lts-and-semver-policy.md`

**Status:** Accepted.

Answers the three operational questions every prospective adopter
asks before committing: what counts as breaking, how long each
release line is supported, and when security fixes backport.

Post-1.0: strict SemVer. Minors ship every ~3 months with a
12-month support window; every fourth minor is an LTS line with
a 24-month window. Majors land no more often than every 12 months
and always publish a migration guide. Deprecations stick for one
full minor cycle before removal. CVEs get patches within 72 hours,
backported to every supported minor.

Pre-1.0 (where we are now): minors may break with a migration note
in the changelog — standard Python pre-1.0 convention. Pin exact
versions in your lockfile until 1.0 ships.

Public API is everything in a module's `__all__` plus what's
re-exported at the top-level `__init__`. Private symbols, deep
imports of submodules, and internal plumbing attributes are
explicitly outside the contract.

---

### ADR-0011: Multi-tenancy

:material-file-document: `docs/adr/0011-multi-tenancy.md`

**Status:** Accepted — Tier A shipped, Tiers B/C designed only.

Three isolation strategies for SaaS workloads, picked per-project
based on blast radius tolerance:

* **Tier A — Column isolation** (shipped). Every tenant-scoped
  row carries `tenant_id`; `TenantMiddleware` resolves the current
  tenant via subdomain / header / path-prefix and binds it to the
  `current_tenant()` contextvar; `TenantScopedMixin` auto-injects
  `WHERE tenant_id = ?` on every `Model.query` so application code
  doesn't have to remember the filter. Lightest footprint, works
  on any SQL engine.
* **Tier B — Schema isolation** (design-only). One PostgreSQL
  schema per tenant via `SET search_path`; migrations fan out
  across schemas. Provides physical row separation without
  per-tenant connection pools. Deferred until a real project
  validates the migration-runner ergonomics.
* **Tier C — Database-per-tenant** (design-only). Separate engine
  per tenant with a lookup-table; strongest isolation, heaviest
  operational cost. Deferred alongside Tier B.

Three resolvers ship with Tier A: `SubdomainTenantResolver`,
`HeaderTenantResolver`, `PathPrefixTenantResolver`. Cache / storage
/ queue scoping follow the same `current_tenant()` lookup so the
common side-effects (cache keys, S3 paths, queue names) don't
leak across tenants.

---

### ADR-0012: Symmetric Encryption Primitive

:material-file-document: `docs/adr/0012-encryption.md`

**Status:** Accepted (retrospective — module shipped alongside the
auth layer).

One symmetric encryption primitive for cookies, small token
payloads, and encrypted config values. AES-256-GCM via the
`cryptography` library, keyed on a Laravel-compatible
`base64:<32 bytes>` `APP_KEY`. `pylar key:generate` emits a fresh
key; `Encrypter.encrypt()` returns a single URL-safe blob of
`nonce || ciphertext || tag`. Tampered ciphertext raises
`DecryptionError` on decrypt rather than silently returning
garbage.

First consumer is `EncryptCookiesMiddleware`, which wraps every
outgoing cookie (minus session + CSRF, which sign separately).
Key rotation via dual keys and KMS integration are intentionally
out of scope for v1 — both slot into a follow-up ADR when a real
operational need lands.

---

### ADR-0013: WebAuthn and Passkeys

:material-file-document: `docs/adr/0013-webauthn-passkeys.md`

**Status:** Proposed — target phase 15 (post-1.0 minor release).

Follow-up to ADR-0009, which deferred WebAuthn explicitly. Adds
phishing-resistant 2FA and a passwordless primary-login path on
top of `py_webauthn`, the canonical Python library.

Decisions:

* `WebauthnServer` service with four async methods — two pairs of
  ceremony helpers (make options / verify response) for registration
  and authentication. No route coupling; apps wire their own
  controllers.
* One polymorphic `pylar_webauthn_credentials` table following the
  same `tokenable_type` / `tokenable_id` pattern as `ApiToken`.
* 2FA integration reuses the existing `Required2FAMiddleware`: any
  enrolled WebAuthn credential *or* confirmed TOTP satisfies the
  check, so users pick their factor.
* `rp_id` is load-bearing and set at boot — WebAuthn binds
  credentials to the exact RP ID, moving domains invalidates every
  passkey.
* Attestation defaults to `"none"` (GitHub / Google posture); FIDO
  MDS integration slots into phase 15d behind a config flag.

Phases: 15a ships 2FA + model + ceremonies; 15b adds passwordless
primary flow; 15c brings `pylar-admin` credential-management UI;
15d is optional enterprise attestation. 15a + 15b land together.
