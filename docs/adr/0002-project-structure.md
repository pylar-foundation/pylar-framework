# ADR-0002: Project structure

## Status

Accepted.

## Context

With the principles from ADR-0001 fixed, we need a top-level layout for the
framework package and for the user project that pylar generates. The layout
must make module boundaries obvious, mirror the user mental model coming
from Laravel, and avoid the historical grab-bag of `support/`-style helpers.

## Decision

### Framework layout

```
pylar/
├── pyproject.toml
└── pylar/
    ├── foundation/      # Application, ServiceProvider, Container, lifecycle
    ├── http/            # Request, Response, Middleware, HttpKernel
    ├── routing/         # Router, Route, RouteGroup, model binding
    ├── database/        # Model, QuerySet, migrations, schema (over SQLAlchemy)
    ├── validation/      # Form Requests / DTOs
    ├── auth/            # Guards, Policies, Gates
    ├── queue/           # Jobs, Workers, Dispatcher
    ├── events/          # Event dispatcher, listeners
    ├── mail/
    ├── notifications/
    ├── cache/
    ├── storage/         # Filesystem abstraction
    ├── console/         # CLI, make: commands
    ├── scheduling/
    ├── broadcasting/
    ├── admin/           # Django-style admin (later phase)
    ├── views/           # Jinja2 + components
    ├── config/          # Config loader, BaseConfig, env helper
    ├── testing/
    └── support/         # Typed Collection / Pipeline only — NOT a junk drawer
```

### User project layout

```
myapp/
├── app/
│   ├── http/
│   │   ├── controllers/
│   │   ├── middleware/
│   │   └── requests/    # DTOs / Form Requests
│   ├── models/
│   ├── policies/
│   ├── jobs/
│   ├── events/
│   ├── listeners/
│   ├── mail/
│   ├── providers/       # AppServiceProvider, RouteServiceProvider
│   └── console/commands/
├── config/              # Modular configs replacing settings.py
│   ├── app.py
│   ├── database.py
│   └── ...
├── database/
│   ├── migrations/
│   ├── seeders/
│   └── factories/
├── resources/
│   ├── views/
│   └── lang/
├── routes/
│   ├── web.py
│   ├── api.py
│   └── console.py
├── storage/
├── tests/
└── pylar                # CLI entrypoint
```

### Module boundary rules

* `foundation/` is the bottom of the stack. It must not import from any other
  pylar module at module-load time. The integration with `config/` lives
  inside `Application.bootstrap` as a local import to break the cycle.
* `http/` re-exports Starlette types (`Request`, response classes) so that
  user code never imports Starlette directly.
* `routing/` depends on `http/` and `foundation/`, never the other way around.
* `support/` may contain only typed generic data structures (`Collection[T]`,
  `Pipeline[T]`, `LazyCollection[T]`). It is **not** a place for `Str.snake()`
  or other facade-style helpers; those belong to specialised modules.
* `signals/` was deleted from the design. Model lifecycle hooks live inside
  `database/model.py` as Laravel-style observers — see ADR-0003.

### Lifecycle (recap of the design that drives the layout)

```
Application(__init__)
  └─ load configs from config/ via pydantic (fail-fast)

Application.bootstrap()
  ├─ ConfigLoader.bind_into(container)
  ├─ instantiate every ServiceProvider listed in AppConfig.providers
  ├─ provider.register(container)        # phase 1 — bindings only
  └─ await provider.boot(container)      # phase 2 — side effects

Application.run(kernel)
  ├─ HttpKernel  → ASGI server
  ├─ ConsoleKernel → CLI command
  └─ QueueKernel → worker loop

Application.shutdown()
  └─ await provider.shutdown(container) in reverse order
```

## Consequences

* `database/` collects ORM, migrations and schema in one place; we accept
  the larger module size in exchange for a single domain boundary.
* `foundation/` cannot grow — anything new belongs to a dedicated module.
* `support/` will need active gatekeeping in code review to stay disciplined.
