# Architecture Review

This page provides a high-level overview of how pylar's modules layer together,
how the container and provider system works, and the design decisions that shape
the framework.

## Layering

Pylar follows a strict dependency direction. Lower layers never import from
higher layers.

```
foundation/          <-- bottom of the stack (Container, Application, ServiceProvider)
  |
config/              <-- pydantic-based config loading, env helper
  |
http/                <-- Starlette re-exports (Request, Response), HttpKernel, Pipeline
  |
routing/             <-- Router, RouteGroup, Action, RoutesCompiler
  |
+-- validation/      <-- RequestDTO auto-resolution, 422 rendering
+-- auth/            <-- Guards, Policies, Gates, AuthMiddleware, 403 rendering
+-- session/         <-- Session, SessionMiddleware, cookie stores
  |
database/            <-- Model, Manager, QuerySet (F/Q), observers, migrations
  |
+-- events/          <-- Event, Listener[EventT], EventBus
+-- queue/           <-- Job[PayloadT], Dispatcher, Worker
+-- cache/           <-- CacheStore Protocol, Cache facade, MemoryCacheStore
+-- storage/         <-- FilesystemStore Protocol, LocalStorage
+-- scheduling/      <-- Schedule, CommandTask, CallableTask
+-- mail/            <-- Mailable, Mailer, transports (SMTP, Log, Memory)
+-- notifications/   <-- Notification, Notifiable, channels
+-- broadcasting/    <-- WebSocket, Broadcaster Protocol
+-- views/           <-- ViewRenderer Protocol, JinjaRenderer
+-- i18n/            <-- Translator, JSON catalogue loader
+-- console/         <-- Command[InputT], ConsoleKernel, make: generators
  |
testing/             <-- create_test_app, http_client, Factory, fakes
```

## The Container-Provider-Kernel pattern

Three concepts drive the entire runtime:

**Container** -- A typed IoC container keyed by `type[T]`, not strings. It
auto-wires constructors by inspecting type hints and refuses to resolve
anything that lacks them. Three lifetimes: `TRANSIENT` (default), `SINGLETON`,
and `SCOPED` (per `with container.scope():`).

**ServiceProvider** -- Each module ships a provider that binds its contracts
into the container. Providers are listed by import in `config/app.py` -- there
is no autodiscovery. Each provider has three lifecycle methods:

- `register(container)` -- sync, bindings only, no I/O.
- `boot(container)` -- async, side effects allowed.
- `shutdown(container)` -- async, cleanup in reverse order.

**Kernel** -- The entry point that the `Application` runs. Three variants:

- `HttpKernel` -- exposes a Starlette ASGI app.
- `ConsoleKernel` -- dispatches CLI commands.
- `QueueKernel` -- runs the worker loop.

## Two-phase lifecycle

The split between `register` and `boot` is deliberate. During `register`,
every provider binds its types into the container. During `boot`, providers
can resolve types that other providers registered -- regardless of
registration order. This eliminates ordering dependencies between modules.

```
Application.__init__()
  -> load configs from config/ via pydantic (fail-fast)

Application.bootstrap()
  -> ConfigLoader.bind_into(container)
  -> instantiate every ServiceProvider listed in AppConfig.providers
  -> provider.register(container)        # phase 1 -- bindings only
  -> await provider.boot(container)      # phase 2 -- side effects

Application.run(kernel)
  -> HttpKernel  -> ASGI server
  -> ConsoleKernel -> CLI command
  -> QueueKernel -> worker loop

Application.shutdown()
  -> await provider.shutdown(container)  # reverse order
```

## Ambient state

Two `contextvars.ContextVar`-backed ambient values exist by design:

| Variable                          | Set by                                        | Purpose                          |
|-----------------------------------|-----------------------------------------------|----------------------------------|
| `pylar.database.current_session`  | `use_session()` / `DatabaseSessionMiddleware` | Ambient SQLAlchemy async session |
| `pylar.auth.current_user`         | `authenticate_as()` / `AuthMiddleware`        | Currently authenticated user     |

These are **not facades**. They have explicit setters, are scoped to the
current async context, and raise clear errors when accessed outside an open
scope. The design keeps controller signatures clean while remaining fully
type-safe and testable.

## Error rendering

Global error handling lives in `pylar/routing/compiler.py`, not in Starlette
exception middleware:

- `ValidationError` from `pylar.validation` renders as `JsonResponse({"errors": [...]}, 422)`
- `AuthorizationError` from `pylar.auth` renders as `JsonResponse({"error": ability}, 403)`

New global error handlers should be added in the same location to maintain
symmetry.

## Module shape

Every module follows a consistent internal structure:

| File              | Purpose                                                    |
|-------------------|------------------------------------------------------------|
| `__init__.py`     | Public re-exports only                                     |
| `exceptions.py`   | Module-specific exception hierarchy with a single `*Error` base |
| `provider.py`     | `ServiceProvider` that binds the module's contracts        |
| `drivers/`        | Optional subpackage when a Protocol has multiple implementations |

This uniformity means that once you understand one module, the patterns
generalize to every other module in the framework.

## Design trade-offs

- **Strict typing over convenience.** No facades, no `**kwargs`, no string-based
  config. The onboarding cost is higher but the long-term maintainability is
  better.
- **SQLAlchemy exposed, not hidden.** The `Manager`/`QuerySet` layer is a
  convenience, not a wall. Users can drop to raw SA expressions at any time.
- **Custom CLI over click/typer.** More maintenance, but the framework controls
  type signatures end-to-end.
- **Python 3.12 floor.** Non-negotiable for PEP 695 generics syntax that the
  entire container and factory system depends on.
