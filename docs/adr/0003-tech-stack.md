# ADR-0003: Technology stack

## Status

Accepted.

## Context

ADR-0001 and ADR-0002 fix the principles and the layout, but they leave open
which third-party libraries pylar will be built on. We needed to lock those
choices before writing more than a single module, because they shape the
public types of every layer above them.

## Decision

| # | Concern | Choice | Notes |
|---|---|---|---|
| 1 | ORM | **SQLAlchemy 2.0** (typed, async) | Not hidden — `Model(DeclarativeBase)` plus a `Manager` / `QuerySet` layer on top. Users can drop down to raw SA expressions. |
| 2 | HTTP core | **Starlette** (≥ 0.40) | Pylar wraps Starlette as a thin typed surface. We do not write our own ASGI plumbing. |
| 3 | Execution model | **Async-first** | Every contract that touches I/O is `async def`. Sync only where principled (CLI bootstrap, migration scripts). |
| 4 | DTOs / validation | **Pydantic v2** | Used for `BaseConfig`, `RequestDTO`, job payloads. Already industry-standard. |
| 5 | Templating | **Jinja2** (≥ 3.1) | Mature, fast, type stubs available. No homegrown templating. |
| 6 | CLI engine | **Custom thin layer over `argparse`** | `typer` / `click` would force their style and obscure type signatures. |
| 7 | Min Python | **3.12** | Required for PEP 695 generics (`def make[T](...)`), `type` statement, modern `typing`. |
| 8 | Lint / type | **ruff + mypy strict** | `disallow_untyped_defs`, `disallow_any_generics`, `no_implicit_reexport`, `warn_unused_ignores`. |
| 9 | ASGI server | **Not bound** | `pylar.http.kernel.HttpKernel` exposes a Starlette ASGI app; uvicorn is an optional `pylar[serve]` extra. |
| 10 | Migrations | **Alembic** with autogenerate | Wrapped in pylar's `database/` module. |
| 11 | Model events | **Laravel-style observers** on `pylar.database.Model` | Django Signals are explicitly **rejected** as their global / implicit nature contradicts ADR-0001. |
| 12 | Admin panel | **Postponed** | Will be revisited after `database/` lands; design will favour HTMX server-rendered UI when we get to it. |
| 13 | CLI binary | Single `pylar` entrypoint | Globally for `pylar new myapp`, locally as `./pylar` inside a project (Laravel `artisan` style). Same script, behaviour depends on cwd. |

## Open questions intentionally deferred

* The shape of the admin panel UI (HTMX vs SPA — leaning HTMX).
* Whether to support contextual bindings in the container — currently no, may
  be reconsidered if a real use case appears.

## Consequences

* Pylar inherits Starlette's strengths (websockets, mature routing, ASGI
  ecosystem) and its limitations (e.g. middleware constraints) without
  duplicating any of that work.
* SQLAlchemy is exposed rather than hidden — the `Manager` / `QuerySet`
  abstraction is a convenience, not a wall. This keeps the escape hatch open
  for advanced queries.
* The decision to write our own CLI layer means we own that maintenance, but
  we keep the right to enforce our typing rules end-to-end.
* Choosing Python 3.12 as the floor blocks adoption on older systems, but it
  is non-negotiable for the generics syntax that the framework leans on.
