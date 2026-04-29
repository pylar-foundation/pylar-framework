# Pylar

Typed async Python web framework — Laravel ergonomics, Django batteries.

Pylar is a Python 3.12+ web framework built on strict mypy, async-first I/O,
and explicit typed APIs (no `**kwargs` in any public surface). It combines
Laravel's developer experience with Django's included-batteries philosophy,
powered by Starlette, SQLAlchemy 2.0, Pydantic, and Jinja2.

## Highlights

- **Typed IoC container** — bindings keyed by `type[T]`, auto-wiring from constructor type hints, three lifetimes (transient, singleton, scoped)
- **Async everywhere** — every I/O surface is `async def`; sync libraries wrapped via `asyncio.to_thread`
- **SQLAlchemy 2.0 ORM** — `Model` with Django-style `fields`, `QuerySet` with `F`/`Q` expressions, `with_` eager loading, observers, ambient session
- **Pydantic validation** — `RequestDTO` auto-resolved by the router; invalid input returns a structured 422 response
- **Middleware pipeline** — composable `Pipeline` with rate limiting, sessions, database session, and auth built in
- **CLI scaffolding** — 13 `make:*` generators for models, controllers, DTOs, jobs, events, policies, and more
- **Scheduling and queues** — `Schedule` with fluent cron builder, typed `Job[PayloadT]`, background `Worker`
- **Mail and notifications** — `Mailable` with Markdown/HTML templates, `Notification` dispatched through mail/log channels

## Documentation

Full documentation is available at [pylar-foundation.github.io/pylar-framework](https://pylar-foundation.github.io/pylar-framework/).

Build locally:

```bash
pip install mkdocs-material
mkdocs serve
```

## Installation

Python 3.12 or newer is required. [uv](https://github.com/astral-sh/uv) is the recommended tool.

```bash
pip install pylar-framework
```

Install with optional extras as needed:

```bash
pip install pylar-framework[serve,auth,sqlite]
```

Available extras: `serve` (uvicorn), `auth` (argon2), `sqlite` (aiosqlite), `postgres` (asyncpg), `mail-markdown`, `cache-redis`, `session-redis`, `storage-s3`, `faker`.

## Quick start

Define a model:

```python
from pylar.database import Model, TimestampsMixin, fields

class Post(Model, TimestampsMixin):
    class Meta:
        db_table = "posts"

    title = fields.CharField(max_length=200)
    slug = fields.SlugField(max_length=240, unique=True)
    body = fields.TextField()
    published = fields.BooleanField(default=False)
```

Add a validation DTO:

```python
from pydantic import Field
from pylar.validation import RequestDTO

class CreatePostDTO(RequestDTO):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1)
    published: bool = False
```

Register routes:

```python
from pylar.database import DatabaseSessionMiddleware
from pylar.routing import Router

from app.http.controllers.post_controller import PostController

def register(router: Router) -> None:
    api = router.group(prefix="/api", middleware=[DatabaseSessionMiddleware])
    api.get("/posts", PostController.index, name="posts.index")
    api.post("/posts", PostController.store, name="posts.store")
```

Wire providers in `config/app.py`:

```python
from pylar.database import DatabaseServiceProvider
from pylar.foundation import AppConfig
from pylar.http import HttpServiceProvider

config = AppConfig(
    name="blog",
    debug=True,
    providers=(
        DatabaseServiceProvider,
        HttpServiceProvider,
        # ... your providers
    ),
)
```

Run the application:

```bash
pylar serve
```

## Modules

| Module | Description |
|---|---|
| `pylar/foundation/` | `Application`, `Container`, `ServiceProvider`, `Kernel` |
| `pylar/config/` | `BaseConfig`, `ConfigLoader`, `env`, `load_dotenv` |
| `pylar/http/` | Starlette `Request`/responses, `Pipeline` middleware, `HttpKernel` |
| `pylar/routing/` | `Router`, `RouteGroup`, `Action`, `RoutesCompiler` |
| `pylar/validation/` | `RequestDTO`, router-driven auto-resolution with 422 responses |
| `pylar/console/` | `Command[InputT]`, `ConsoleKernel`, `pylar` CLI entrypoint |
| `pylar/database/` | SQLAlchemy 2.0 `Model`, `Manager`, `QuerySet` with `F`/`Q`, observers, `transaction()` |
| `pylar/database/migrations/` | Alembic wrapper: `migrate`, `migrate:rollback`, `migrate:status`, `make:migration` |
| `pylar/auth/` | `Authenticatable`, `Guard`, `SessionGuard`, password hashers, `Policy`, `Gate`, `AuthMiddleware` |
| `pylar/session/` | `Session`, `SessionMiddleware` (signed cookie), memory/file stores |
| `pylar/events/` | `Event`, `Listener[EventT]`, `EventBus`, `EventServiceProvider` |
| `pylar/queue/` | `Job[PayloadT]`, `JobPayload`, `Dispatcher`, `Worker`, `MemoryQueue` |
| `pylar/cache/` | `CacheStore` protocol, `Cache` facade with `remember`, memory/redis stores |
| `pylar/storage/` | `FilesystemStore` protocol, `LocalStorage` (sandboxed), `MemoryStorage` |
| `pylar/scheduling/` | `Schedule`, fluent cron builder, `CommandTask`/`CallableTask` |
| `pylar/views/` | `ViewRenderer` protocol, `JinjaRenderer`, `View` facade |
| `pylar/mail/` | `Mailable`, `ViewMailable`, `MarkdownMailable`, `Attachment`, SMTP/memory/log transports |
| `pylar/notifications/` | `Notification`, `Notifiable`, mail/log channels, `NotificationDispatcher` |
| `pylar/broadcasting/` | `WebSocket`, `Broadcaster` protocol, `MemoryBroadcaster`, `Router.websocket()` |
| `pylar/i18n/` | `Translator` with `with_locale` ambient, JSON catalogue loader |
| `pylar/testing/` | `create_test_app`, `http_client`, `Factory[ModelT]`, `transactional_session` |
| `pylar/console/make/` | 13 generators: model, controller, provider, command, dto, job, event, listener, policy, mailable, notification, factory, observer |
| `pylar/admin/` | Auto-CRUD (coming soon) |

## CLI

```bash
pylar new <name>          # Scaffold a new project
pylar serve               # Start the development server
pylar make:model          # Generate a model (+ 12 other make:* generators)
pylar migrate             # Run pending migrations
pylar queue:work          # Start the background queue worker
pylar schedule:run        # Execute due scheduled tasks
```

## Configuration

Application configuration lives in `config/app.py` using the `AppConfig` dataclass. Providers are listed explicitly by import — no autodiscovery. Environment variables are loaded via `pylar.config.env()` and `load_dotenv()`, with full `.env` file support.

## Contributing

- Run tests: `uv run pytest -q`
- Type-check: `uv run mypy pylar`
- Follow [Conventional Commits](https://www.conventionalcommits.org/) for all commit messages
- Read the ADRs in `docs/adr/` before proposing architectural changes

## License

[MIT](LICENSE)
