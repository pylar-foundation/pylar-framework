# Changelog

Notable user-visible changes per release. See the git history for the
full log.

## Unreleased

### Added

- `docs/CONSTITUTION.md` — distilled meta-index of the load-bearing
  rules every ADR builds on (strict typing, async I/O, no `**kwargs`,
  migration-stub naming, SemVer discipline, testing conventions).
- HTTP error pages — default 4xx/5xx styled pages with
  `register_error_page` + Jinja template overrides.
- Queue recent-jobs history (`RecentJob`, `record_completed`,
  `recent_records`) with TTL retention.
- Queue pagination (`pending_records` / `recent_records` offset
  params + `recent_size`).
- Queue live-worker reporting (`report_worker_count` /
  `worker_counts`) surfaced in the admin.
- Queue supervisor `on_worker_spawn` / `on_scale` hooks.
- `attach_per_job_logging` — Horizon-style per-job lines shared by
  `queue:work` and `queue:supervisor`.
- `Field.comment` — SQL column comment + admin label fallback.
- WebAuthn / passkeys primitive (`pylar.auth.webauthn`): `WebauthnServer`,
  `WebauthnCredential`, `WebauthnConfig`, exceptions rooted at
  `WebauthnError`. Supports both 2FA and passwordless-primary flows
  via `make_authentication_options(user=...)`. Install with
  `pylar[webauthn]`. See ADR-0013 for the design.
- WebAuthn management CLI (ADR-0013 phase 15c): `auth:webauthn:list`,
  `auth:webauthn:revoke <id>`, `auth:webauthn:prune --days N`.
  Wired by the opt-in `WebauthnServiceProvider`.
- WebAuthn admin page: new `/admin/system/webauthn` (linked from the
  System menu as "Passkeys") listing every registered credential
  with inline rename and revoke, powered by
  `GET/PATCH/DELETE /admin/api/system/webauthn`.
- Self-service profile page at `/admin/profile` with passkey
  management — add a passkey in-browser, rename, revoke — reachable
  from the sidebar user label. Backed by
  `GET /admin/api/profile`, `GET/POST /admin/api/profile/webauthn/register/*`,
  `PATCH/DELETE /admin/api/profile/webauthn/{id}`. All endpoints
  strictly scope to the current user; no cross-user access even
  when an id is guessed.
- WebAuthn attestation verifier pluggable (ADR-0013 phase 15d):
  `AttestationVerifier` Protocol with `TrustAnyAttestationVerifier`
  default and a `MetadataServiceAttestationVerifier` that consumes
  a pre-downloaded FIDO MDS3 JSON blob. Enables
  `attestation="direct"` deployments to enforce model-level trust.
- Passkey login for the admin panel: new
  `GET /admin/api/login/webauthn/options` and
  `POST /admin/api/login/webauthn/verify` endpoints plus a
  "Sign in with passkey" button on `/admin/login` that only
  renders when the backend exposes the flow.

### Changed

- Migration stubs (`pylar/auth/stubs/2026_04_01_*.py.stub`) are now
  shipped with canonical date prefixes (`YYYY_MM_DD_HHMMSS_<name>.py.stub`)
  and copied verbatim by `pylar new` — same filename, same
  `Create Date` header, same revision number across every install.
  Deterministic migration ordering regardless of when the project
  was generated. `examples/blog` and `examples/dvozero` are
  refactored to use the new layout (stubs rev `0001`–`0009`, project
  migrations start at `0010`).
- `ASGIThrottleMiddleware` now splits traffic into two rate-limit
  buckets — anonymous (capped at `max_requests`) and likely-
  authenticated (capped at `max_requests × authenticated_multiplier`,
  default 10). A request is considered authenticated when it carries
  either a session cookie or an `Authorization` header. The anon
  bucket keys by client IP; the auth bucket keys by a SHA-256
  fingerprint of the credential itself (cookie value or
  `Authorization` header), so two users behind the same NAT each
  get their own counter. The kernel reads the session cookie name
  from `SessionConfig` when bound, otherwise falls back to
  `pylar_session_id`.

## 0.1.0 — initial public release

First public release of `pylar-framework` and `pylar-admin` on PyPI.
Tag the exact version in your lockfile (`pylar-framework==0.1.0`)
and review release notes before any minor bump — `0.x` allows
breaking changes between minors.

### `pylar dev` — development server (Phase 14)

**Added**

* `pylar dev` — auto-reload development server wrapping
  `uvicorn --reload --factory`.
* `Application.from_config()` classmethod for import-path-driven
  bootstrap (used by the dev command and any ASGI deployment
  that needs a factory callable).

### Multi-tenancy Tier A (ADR-0011, Phase 13b)

**Added**

* `pylar/tenancy/` module: `Tenant` base model, `TenantMiddleware`,
  `current_tenant()` contextvar, `TenantScopedMixin` (column-FK
  auto-scoping).
* Three resolvers: `SubdomainTenantResolver`, `HeaderTenantResolver`,
  `PathPrefixTenantResolver`.
* `TenantServiceProvider`.

Schema-per-tenant (Tier B) and database-per-tenant (Tier C) are
designed in ADR-0011 but deferred to a follow-up.

### LTS + SemVer policy (ADR-0010, Phase 13a)

**Added**

* `support-policy.md` on the docs site.
* ADR-0010 formalises the versioning contract, release cadence, LTS
  lines, deprecation policy, and CVE response commitment.

### Admin actions + permissions (Phase 12)

**Added**

* `@admin_action` decorator + `AdminAction` + `ActionResult` envelope.
* `ExportCsvAction` / `ExportJsonAction` built-in exports.
* `ModelAdmin.actions` tuple + `POST /admin/api/models/{slug}/actions/{name}`.
* `ModelAdmin.permissions: AdminPermissions(view, add, change, delete)` —
  per-model gates for `pylar.auth.roles.Permission`.

### Auth parity (ADR-0009, Phase 11)

**Added**

* **Signed URLs** (`UrlSigner`): HMAC-SHA256, keyed on `APP_KEY`,
  with optional expiry. Primitive for verify/reset/invite flows.
* **API tokens** (Sanctum-style): `ApiToken` model, `TokenMiddleware`
  (bearer), abilities with wildcard/prefix matching, expiry,
  last-used tracking, SHA-256 hashed storage.
* **Email verification + password reset**: `build_verification_url`,
  `build_password_reset_url`, `mark_email_verified`, `reset_password`,
  `RequireVerifiedEmailMiddleware`.
* **2FA TOTP**: RFC 6238 stdlib implementation, `generate_secret`,
  `provisioning_uri` (QR), `verify` with ±1-window drift, recovery
  codes (hashed, single-use).
* **Roles + permissions**: `Role`, `Permission`, `UserRole`,
  `RolePermission` models + `assign_role`, `has_role`,
  `has_permission`, `user_permissions` async helpers. Wildcard
  codes (`posts.*`) mirror the API-token ability model.
* `email_verified_at` field on `BaseUser`.

### Observability (ADR-0008, Phase 9)

**Added**

* `pylar about` — config dump (application, database, cache, queue,
  providers, routing, scheduled tasks). DSN passwords masked.
* `pylar doctor` — probes DB/cache/queue/storage/mail/migrations;
  exit code 1 on any failure. CI-ready readiness gate.
* `install_json_logging()` — one-line structured JSON logs with
  request-id correlation from `RequestIdMiddleware`.
* `pylar[otel]` extras: `OtelServiceProvider` + `OtelJobMiddleware` +
  env-driven OTLP exporter.
* `pylar[prometheus]` extras: `PrometheusMiddleware` +
  `PrometheusJobMiddleware` + `GET /metrics`.
* `pylar[sentry]` extras: `SentryServiceProvider` +
  `SentryHttpMiddleware` + `SentryJobMiddleware`.

### PusherBroadcaster (Phase 10)

**Added**

* `PusherBroadcaster` — HMAC-signed REST publish to Pusher Channels.
  `pylar[broadcast-pusher]` extras (httpx). Server-side subscribe
  raises `PusherSubscribeNotSupported` (clients use Pusher's
  WebSocket edge).

### API layer & OpenAPI (ADR-0007, Phase 7)

**Added**

* `pylar.api` module with `ApiError`, `ApiErrorMiddleware`, `Page[T]`,
  `ApiServiceProvider`, `ApiDocsConfig`.
* `GET /openapi.json`, `GET /docs` (Swagger UI), `GET /redoc` — mounted
  automatically by `ApiServiceProvider`.
* `pylar api:docs [--output path]` console command.
* Auto-serialisation of pydantic return values in the routing
  compiler — controllers can return `BaseModel`, `list[BaseModel]`,
  or `Page[T]` and the framework wraps them in `JsonResponse`.
* OpenAPI 3.1 generator derives spec from Router + handler type hints.
* `servers` tuple on `ApiDocsConfig` for Swagger UI base-URL dropdown.

**Migration**

No breaking changes. Existing controllers that return `Response`
continue to work unchanged.

### Multi-queue architecture (ADR-0006)

**Added**

* `JobRecord.queue`, `Job.queue` class-level default, `queue=` override
  on `Dispatcher.dispatch`.
* `JobQueue.pop(queues=(…))` for priority-ordered pops.
* `JobQueue.size(queue)` for backlog inspection.
* `QueueConfig` (tries / timeout / backoff / min_workers /
  max_workers / scale_threshold / scale_cooldown_seconds).
* `QueuesConfig` mapping with `DEFAULT_QUEUES` for `high`/`default`/
  `low`.
* `Job.tries`, `Job.timeout` class-level overrides (Laravel-parity).
* `QueueSupervisor` autoscaling pool.
* `queue:run`, `queue:forget`, `queue:flush`, `queue:clear`,
  `queue:prune-failed`, `queue:supervisor` commands.
* `--queue=high,default,low` on `queue:work` and `queue:run`.

**Migration**

The `DatabaseQueue` driver gains a `queue` column on both
`pylar_jobs` and `pylar_failed_jobs`. If you have a pre-existing
database with queue data, hand-add the column:

```sql
ALTER TABLE pylar_jobs
  ADD COLUMN queue VARCHAR(64) NOT NULL DEFAULT 'default';
ALTER TABLE pylar_failed_jobs
  ADD COLUMN queue VARCHAR(64) NOT NULL DEFAULT 'default';
CREATE INDEX idx_pylar_jobs_queue ON pylar_jobs(queue);
```

### Runtime ambient sessions

**Added**

* `pylar.database.ambient_session(manager)` — reuse existing session
  if set, otherwise open a fresh one.
* `Worker._process`, `SchedulerKernel.run`, `ConsoleKernel._dispatch`
  now open an ambient session around each invocation.

### Console Rich output

**Changed**

Every built-in command routes messages through `Output` (Rich-powered).
Command constructors take `Output` as a dependency — test code that
instantiated `CacheClearCommand(cache)` now needs
`CacheClearCommand(cache, Output(buf, colour=False))`.

### Migrations polish

**Fixed**

* `migrate:rollback` on an empty database prints `Nothing to rollback.`
  instead of an Alembic traceback.
* `migrate:status` lists revisions oldest-first (HEAD at the bottom).

## Older releases

See the git history for pre-0.3 changes.
