# API Reference

Module-by-module listing of pylar's public API. Each entry shows the public
re-exports from each module's `__init__.py`.

## API Layer

`from pylar.api import ...` (ADR-0007)

| Class / Function         | Description                                              |
|--------------------------|----------------------------------------------------------|
| `ApiServiceProvider`     | Registers the API layer + mounts `/openapi.json`, `/docs`, `/redoc` |
| `ApiDocsConfig`          | Toggle + metadata for the docs portal                     |
| `ApiError`               | Raise for semantic errors — rendered into the phase-7 envelope |
| `ApiErrorMiddleware`     | Converts domain exceptions to JSON envelopes             |
| `Page[T]`                | Generic pagination envelope (`{data, meta, links}`)      |
| `generate_openapi`       | Walk a `Router` and return the OpenAPI 3.1 dict          |
| `render_api_response`    | Wrap a pydantic-shaped return value in `JsonResponse`    |
| `render_api_error`       | Render a domain exception as JSON                        |

## Foundation

`from pylar.foundation import ...`

| Class / Function   | Description                                              |
|--------------------|----------------------------------------------------------|
| `Application`      | Core application instance -- bootstraps, runs, shuts down |
| `Container`        | Typed IoC container keyed by `type[T]` with auto-wiring  |
| `ServiceProvider`  | Base class for module providers (`register`/`boot`/`shutdown`) |
| `AppConfig`        | Pydantic model for top-level app configuration           |

## Config

`from pylar.config import ...`

| Class / Function | Description                                          |
|------------------|------------------------------------------------------|
| `BaseConfig`     | Pydantic base for typed config sections              |
| `ConfigLoader`   | Loads and binds config objects from `config/` directory |
| `env`            | Read an environment variable with type coercion      |
| `load_dotenv`    | Parse `.env` files into the process environment      |

## HTTP

`from pylar.http import ...`

| Class / Function | Description                                          |
|------------------|------------------------------------------------------|
| `HttpKernel`     | Builds the ASGI app from the router and middleware   |
| `Request`        | Starlette `Request` re-export                        |
| `JsonResponse`   | Starlette `JSONResponse` re-export                   |
| `Pipeline`       | Middleware pipeline for request/response processing   |

## Routing

`from pylar.routing import ...`

| Class / Function | Description                                          |
|------------------|------------------------------------------------------|
| `Router`         | Register routes and route groups                     |
| `RouteGroup`     | Group routes under a shared prefix and middleware    |
| `Action`         | Binds a route to a controller method                 |
| `RoutesCompiler` | Compiles routes into a Starlette ASGI application    |

## Validation

`from pylar.validation import ...`

| Class / Function   | Description                                        |
|--------------------|----------------------------------------------------|
| `RequestDTO`       | Pydantic base for request validation (auto 422)    |
| `ValidationError`  | Raised on invalid input, rendered as 422 JSON      |

## Database

`from pylar.database import ...`

| Class / Function     | Description                                        |
|----------------------|----------------------------------------------------|
| `Model`              | SQLAlchemy `DeclarativeBase` subclass with extras  |
| `Manager`            | Per-model query entry point                        |
| `QuerySet`           | Chainable query builder with `F`, `Q`, `with_`     |
| `transaction`        | Async context manager for explicit transactions    |
| `current_session`    | Ambient `ContextVar`-backed async session accessor |

## Auth

`from pylar.auth import ...`

| Class / Function     | Description                                        |
|----------------------|----------------------------------------------------|
| `Authenticatable`    | Protocol for user models                           |
| `Guard`              | Base class for authentication guards               |
| `SessionGuard`       | Session-based authentication                       |
| `Policy`             | Per-model authorization policy                     |
| `Gate`               | Central authorization registry                     |
| `AuthMiddleware`     | Middleware that populates `current_user`            |

## Events

`from pylar.events import ...`

| Class / Function | Description                                          |
|------------------|------------------------------------------------------|
| `Event`          | Base class for domain events                         |
| `Listener`       | Generic `Listener[EventT]` base                      |
| `EventBus`       | Dispatches events to registered listeners            |

## Queue

`from pylar.queue import ...`

| Class / Function | Description                                          |
|------------------|------------------------------------------------------|
| `Job`            | Generic `Job[PayloadT]` base class                   |
| `JobPayload`     | Pydantic base for typed job payloads                 |
| `Dispatcher`     | Pushes jobs onto a queue backend                     |
| `Worker`         | Processes jobs from a queue backend                  |
| `MemoryQueue`    | In-process queue for testing and development         |

## Mail

`from pylar.mail import ...`

| Class / Function     | Description                                        |
|----------------------|----------------------------------------------------|
| `Mailable`           | Base class for composing email messages             |
| `ViewMailable`       | Mailable rendered from a Jinja2 template           |
| `MarkdownMailable`   | Mailable rendered from Markdown content            |
| `Mailer`             | Sends mailables through a configured transport     |
| `SmtpTransport`      | SMTP transport (async via `to_thread`)             |

## Other modules

| Module             | Key exports                                            |
|--------------------|--------------------------------------------------------|
| `pylar.cache`      | `CacheStore` Protocol, `Cache` facade, `MemoryCacheStore` |
| `pylar.storage`    | `FilesystemStore` Protocol, `LocalStorage`, `MemoryStorage` |
| `pylar.session`    | `Session`, `SessionMiddleware`, `MemoryStore`, `FileStore` |
| `pylar.scheduling` | `Schedule`, `CommandTask`, `CallableTask`              |
| `pylar.views`      | `ViewRenderer` Protocol, `JinjaRenderer`, `View` facade |
| `pylar.notifications` | `Notification`, `Notifiable`, `MailChannel`, `LogChannel` |
| `pylar.broadcasting`  | `Broadcaster` Protocol, `MemoryBroadcaster`, `Router.websocket()` |
| `pylar.i18n`       | `Translator`, `with_locale`, JSON catalogue loader     |
| `pylar.console`    | `Command[InputT]`, `ConsoleKernel`, 13 `make:` generators |
| `pylar.testing`    | `create_test_app`, `http_client`, `Factory[ModelT]`, fakes |
