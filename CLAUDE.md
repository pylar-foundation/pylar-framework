# pylar — context for Claude sessions

A typed, async-first Python web framework that combines Laravel's
ergonomics with Django's batteries. Strict mypy, no `**kwargs` in any
public API, async I/O everywhere, explicit imports over string-based
discovery.

If you are a Claude session reading this file: **read the ADRs in
`docs/adr/` before suggesting any architectural change**. They are the
source of truth for every decision the codebase makes about layering,
typing, and dependencies. The per-module backlog notes under
`docs/todo/` describe deferred work and the rationale behind every
"future hook" — consult them before suggesting features that look
missing.

## Repository layout

```
pylar/
├── docs/
│   ├── adr/      Architecture Decision Records (read first)
│   └── todo/     Per-module backlog notes
├── pylar/        The framework package
├── tests/        pytest suite mirroring the package layout
└── examples/
    └── blog/     End-to-end reference application — read this when
                  you need to see every layer wired together
```

Inside `pylar/` every module follows the same shape:

* `__init__.py` — public re-exports only.
* `exceptions.py` — module-specific exception hierarchy with a single
  `*Error` base.
* A small set of focused files (one concept per file).
* `provider.py` — the `ServiceProvider` that binds the module's
  contracts into the container during the application lifecycle.
* Optional `drivers/` subpackage when the module exposes a Protocol
  with multiple implementations (cache, storage, mail, queue).

## Module map

| Module | Status | Notes |
|---|---|---|
| `pylar/foundation/` | done | `Application`, `Container`, `ServiceProvider`, `Kernel` |
| `pylar/config/` | done | `BaseConfig`, `ConfigLoader`, `env`, `load_dotenv` |
| `pylar/http/` | done | Re-exports of Starlette `Request` / responses, `Pipeline` middleware, `HttpKernel` |
| `pylar/routing/` | done | `Router`, `RouteGroup`, `Action`, `RoutesCompiler` |
| `pylar/validation/` | done | `RequestDTO`, router-driven auto-resolution → 422 |
| `pylar/console/` | done | `Command[InputT]`, `ConsoleKernel`, `pylar` entrypoint |
| `pylar/database/` | done | SQLAlchemy 2.0: `Model`, `Manager`, `QuerySet` (`F`/`Q`, `with_`), observers, ambient session, `transaction()` |
| `pylar/database/migrations/` | done | Alembic wrapper + `migrate` / `migrate:rollback` / `migrate:status` / `make:migration` |
| `pylar/auth/` | done | `Authenticatable`, `Guard`, `SessionGuard`, `Argon2`/`Pbkdf2PasswordHasher`, `Policy`, `Gate`, `AuthMiddleware` → 403 |
| `pylar/session/` | done | `Session`, `SessionMiddleware` (signed cookie), `Memory`/`File` stores |
| `pylar/events/` | done | `Event`, `Listener[EventT]`, `EventBus`, `EventServiceProvider` |
| `pylar/queue/` | done | `Job[PayloadT]`, `JobPayload`, `Dispatcher`, `Worker`, `MemoryQueue`, `queue:work` |
| `pylar/cache/` | done | `CacheStore` Protocol + `Cache` facade with `remember`, `MemoryCacheStore` |
| `pylar/storage/` | done | `FilesystemStore` Protocol, `LocalStorage` (sandboxed), `MemoryStorage` |
| `pylar/scheduling/` | done | `Schedule`, fluent builder, `CommandTask` / `CallableTask`, `schedule:run` / `schedule:list` |
| `pylar/views/` | done | `ViewRenderer` Protocol, `JinjaRenderer`, `View` facade |
| `pylar/mail/` | done | `Mailable`, `ViewMailable`, `MarkdownMailable`, `Attachment` (inline/CID), `Mailer.queue` + `SendMailableJob`, `MemoryTransport` / `LogTransport` / `SmtpTransport` |
| `pylar/notifications/` | done | `Notification`, `Notifiable`, `MailChannel`, `LogChannel`, `NotificationDispatcher` |
| `pylar/broadcasting/` | done | `WebSocket` re-export, `Broadcaster` Protocol, `MemoryBroadcaster`, `Router.websocket()` |
| `pylar/i18n/` | done | `Translator` with `with_locale` ambient, JSON catalogue loader |
| `pylar/testing/` | done | `create_test_app`, `http_client`, `Factory[ModelT]`, `transactional_session` |
| `pylar/console/make/` | done | 16 generators (model / controller / provider / command / dto / job / event / listener / policy / mailable / notification / factory / observer / middleware / test / seeder) + `MakeServiceProvider` |
| `pylar/api/` | done | `ApiServiceProvider`, `Page[T]` pagination envelope, OpenAPI 3.1 generator, `/openapi.json` + `/docs` + `/redoc`, auto-serialization of Pydantic returns (ADR-0007) |
| `pylar/observability/` | done | `pylar about` / `pylar doctor`, JSON logging, `Otel` / `Prometheus` / `Sentry` providers behind opt-in extras (ADR-0008) |
| `pylar/encryption/` | done | `Encrypter` (AES-256-GCM), `pylar key:generate`, `EncryptCookiesMiddleware` (ADR-0012) |
| `pylar/tenancy/` | tier A | `Tenant`, `TenantMiddleware`, `current_tenant()`, `TenantScopedMixin`, subdomain/header/path resolvers. Tiers B+C deferred by design (ADR-0011) |
| `pylar/support/` | done | Typed generic helpers used across modules (no I/O, no framework deps) |
| `pylar/admin/` | extracted | Re-export shim → `pylar-admin` package (see `pylar-admin/` in repo root) |

## Conventions

### Code style

* **No code duplication.** If two places need the same logic, extract
  it into a shared function, method, or delegate to an existing
  command. When a command needs the behaviour of another command, it
  instantiates and calls it rather than copying the body. This rule
  applies everywhere — controllers, commands, providers, drivers.

### Typing

* Strict `mypy` is configured in `pyproject.toml` with
  `disallow_untyped_defs`, `disallow_any_generics`, `strict_optional`,
  and `no_implicit_reexport`. Every commit must pass it.
* Generics use PEP 695 syntax (`def make[T](...)`); minimum Python
  version is 3.12.
* `**kwargs` is **forbidden in public APIs**. The container's resolver
  refuses to wire a constructor that uses `*args` / `**kwargs` and
  raises a `ResolutionError` instead. Internal helpers (e.g.
  `Container.call(target, params={...})`) may use named runtime
  parameters; this is not the same as `**kwargs` because the keys are
  resolved against the target's typed signature.
* String identifiers for classes (`"app.models.User"`) are forbidden.
  Always import the class.

### Async

* Every I/O surface is `async def`. Sync code is allowed only where
  async makes no sense (CLI bootstrap, migration scripts, the cron
  expression matcher, the in-memory cache).
* Sync libraries are wrapped via `asyncio.to_thread` so the surface
  stays async (`storage.LocalStorage`, `mail.SmtpTransport`,
  `database.migrations.MigrationsRunner`).
* Lifecycle methods on `ServiceProvider` are split: `register` is sync
  (bindings only, no I/O), `boot` is async (side effects allowed),
  `shutdown` is async.

### Containers and providers

* Pylar's IoC container is **typed**. Bindings are keyed by `type[T]`,
  not strings. The auto-wiring resolver inspects constructor type
  hints and refuses to instantiate anything that lacks them.
* Three lifetimes: `TRANSIENT` (default), `SINGLETON`,
  `SCOPED` (per `with container.scope():`).
* `Container.call(target, *, overrides, params)` invokes a callable
  with auto-resolved arguments. `overrides` injects by type,
  `params` by parameter name. Used by routing and the console kernel.
* Service providers are listed by import inside `config/app.py`. No
  autodiscover.
* The two-phase lifecycle (`register` → `boot`) lets providers
  reference each other in `boot` regardless of registration order.

### Ambient state

Two ambient context variables exist on purpose:

* `pylar.database.current_session()` — bound by `use_session()` /
  `DatabaseSessionMiddleware`.
* `pylar.auth.current_user()` — bound by `authenticate_as()` /
  `AuthMiddleware`.

These are *not* facades. They are `contextvars.ContextVar`-backed
ambient state with explicit setters and clear errors when accessed
outside of an open scope.

### Errors and HTTP rendering

* `pylar.validation.ValidationError` is caught by `RoutesCompiler`
  and rendered as `JsonResponse({"errors": [...]}, 422)`.
* `pylar.auth.AuthorizationError` is caught by the same compiler and
  rendered as `JsonResponse({"error", "ability"}, 403)`.
* Both error paths are symmetric and live in
  `pylar/routing/compiler.py`. Add new global error handlers in the
  same place rather than installing Starlette exception middleware.

### Tests

* `pytest-asyncio` in `auto` mode — all `async def` tests are
  recognised automatically; do not add `@pytest.mark.asyncio`.
* Tests live under `tests/<module>/` and the import path
  `tests.<module>` is used to import shared helpers across files.
* Database tests use `sqlite+aiosqlite:///:memory:` via `conftest.py`
  fixtures (`manager`, `session`).
* HTTP tests drive the kernel via `httpx.ASGITransport` — no real
  server, no uvicorn.

### Documentation

* Every public class / function has a docstring that explains both
  *what* it does and *why* it's shaped that way. The "why" is the
  important half — the codebase deliberately avoids facade-style
  shortcuts and the docstrings need to reinforce the rationale.
* Architectural decisions go into `docs/adr/`. Future-work entries
  go into `docs/todo/`. Neither directory is a changelog — when an
  ADR is superseded, write a new ADR; when a backlog item is picked
  up, **delete** it.

## Dependencies (pyproject.toml)

Core deps are pinned with lower bounds, no upper bounds:

* `starlette`, `sqlalchemy[asyncio]`, `pydantic`, `jinja2`,
  `alembic`, `python-multipart`, `croniter`.

Optional extras:

* `pylar[serve]` — `uvicorn`, used by `HttpKernel.handle()`.
* `pylar[dev]` — `pytest`, `pytest-asyncio`, `mypy`, `ruff`,
  `httpx`, `aiosqlite`.

When adding a new dependency: prefer the smallest battle-tested option
and document the choice in an ADR.

## Workflow notes

* The framework is being built one module at a time. Each module ships
  with: code + tests + ADR-aligned docstrings + a `docs/todo/<module>.md`
  file capturing whatever was deferred.
* After a module is done it gets committed as `feat(<module>): ...` with
  a multi-paragraph message describing intent. The git history is the
  primary record of *why* the codebase looks the way it does.
* Tests should be runnable with `uv run pytest -q` (the project uses
  `uv` for Python and dependency management). `uv run mypy pylar`
  must stay clean.
* Never bypass `--no-verify` or skip hooks. If something fails in CI,
  fix the underlying issue.

## When in doubt

1. Read the matching ADR in `docs/adr/`.
2. Read the matching backlog file in `docs/todo/`.
3. Read the existing module that solves the closest analogous problem
   — every layer follows the same shape and the patterns generalise.
4. If there is still ambiguity, ask the human before writing code.
