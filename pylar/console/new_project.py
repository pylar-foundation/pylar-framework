"""``pylar new <name>`` — scaffold a fresh project from scratch.

Creates a full Laravel-style directory tree with a working
``config/app.py``, database config, route files, a base layout
template, and a ``.env`` stub. The generated project is immediately
runnable with ``pylar migrate && pylar serve``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from textwrap import dedent

# ------------------------------------------------------------------- templates

_CONFIG_APP = dedent('''\
    """Top-level application configuration."""

    from __future__ import annotations

    from pylar.api import ApiServiceProvider
    from pylar.auth.provider import AuthServiceProvider
    from pylar.cache import CacheServiceProvider
    from pylar.console.make import MakeServiceProvider
    from pylar.database import DatabaseServiceProvider
    from pylar.database.migrations import MigrationsServiceProvider
    from pylar.encryption import EncryptionServiceProvider
    from pylar.foundation import AppConfig
    from pylar.http import HttpServiceProvider
    from pylar.observability import ObservabilityServiceProvider
    from pylar.queue import QueueServiceProvider
    from pylar.session import SessionServiceProvider
    from pylar.storage import StorageServiceProvider
    from pylar.views import ViewServiceProvider

    from app.providers.app_service_provider import AppServiceProvider
    from app.providers.route_service_provider import RouteServiceProvider

    config = AppConfig(
        name="${name}",
        debug=True,
        # Installed pylar packages (pip/uv) are auto-discovered via entry
        # points and appended after the providers below.  Set
        # autodiscover=False to disable.
        providers=(
            DatabaseServiceProvider,
            MigrationsServiceProvider,
            CacheServiceProvider,
            EncryptionServiceProvider,
            SessionServiceProvider,
            StorageServiceProvider,
            HttpServiceProvider,
            QueueServiceProvider,
            ApiServiceProvider,
            ViewServiceProvider,
            MakeServiceProvider,
            ObservabilityServiceProvider,
            AuthServiceProvider,
            AppServiceProvider,
            RouteServiceProvider,
        ),
    )
''')

_CONFIG_DATABASE = dedent('''\
    """Database connection configuration."""

    from __future__ import annotations

    from pylar.config import env
    from pylar.database import DatabaseConfig

    config = DatabaseConfig(
        url=env.str("DATABASE_URL", "sqlite+aiosqlite:///./database.sqlite"),
        echo=env.bool("DB_ECHO", False),
    )
''')

_APP_PROVIDER = dedent('''\
    """Application service provider — gate, policies, observers."""

    from __future__ import annotations

    from pylar.config import env
    from pylar.foundation import Container, ServiceProvider
    from pylar.session import SessionConfig
    from pylar.storage import StorageConfig


    class AppServiceProvider(ServiceProvider):
        def register(self, container: Container) -> None:
            container.instance(
                SessionConfig,
                SessionConfig(
                    secret_key=env.str("SESSION_SECRET"),
                    cookie_secure=False,
                ),
            )
            container.instance(
                StorageConfig,
                StorageConfig(root="./storage", base_url="/files"),
            )

        async def boot(self, container: Container) -> None:
            pass
''')

_ROUTE_PROVIDER = dedent('''\
    """Loads the application's routes into the container."""

    from __future__ import annotations

    from pylar.foundation import Container, ServiceProvider
    from pylar.routing import Router


    class RouteServiceProvider(ServiceProvider):
        def register(self, container: Container) -> None:
            from routes import api, web

            router = Router()
            api.register(router)
            web.register(router)
            container.singleton(Router, lambda: router)
''')

_ROUTES_WEB = dedent('''\
    """Server-rendered web routes."""

    from __future__ import annotations

    from pylar.database import DatabaseSessionMiddleware
    from pylar.http import Request, Response
    from pylar.routing import Router
    from pylar.views import View


    async def home(request: Request, view: View) -> Response:
        return await view.make("home.html", {"title": "Welcome"})


    def register(router: Router) -> None:
        web = router.group(middleware=[DatabaseSessionMiddleware])
        web.get("/", home, name="home")
''')

_ROUTES_API = dedent('''\
    """JSON API routes."""

    from __future__ import annotations

    from pylar.database import DatabaseSessionMiddleware
    from pylar.http import Request, Response, json
    from pylar.routing import Router


    async def ping(request: Request) -> Response:
        return json({"status": "ok"})


    def register(router: Router) -> None:
        api = router.group(prefix="/api", middleware=[DatabaseSessionMiddleware])
        api.get("/ping", ping, name="api.ping")
''')

_LAYOUT = dedent('''\
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>{% block title %}${name}{% endblock %}</title>
        <style>
            body {
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
                max-width: 720px;
                margin: 0 auto;
                padding: 2rem 1.25rem 4rem;
                line-height: 1.6;
                color: #1c1c1e;
                background: #fbfbfd;
            }
            a { color: #0066cc; text-decoration: none; }
            a:hover { text-decoration: underline; }
        </style>
    </head>
    <body>
        {% block content %}{% endblock %}
    </body>
    </html>
''')

_HOME = dedent('''\
    {% extends "layouts/app.html" %}

    {% block content %}
    <h1>Welcome to ${name}</h1>
    <p>Your pylar project is ready. Edit <code>routes/web.py</code> to start building.</p>
    <ul>
        <li><a href="/api/ping">GET /api/ping</a> &mdash; JSON health check</li>
    </ul>
    {% endblock %}
''')

_ENV = dedent('''\
    APP_KEY=${app_key}
    DATABASE_URL=sqlite+aiosqlite:///./database.sqlite
    DB_ECHO=false
    SESSION_SECRET=${session_secret}
''')

_GITIGNORE = dedent('''\
    __pycache__/
    *.pyc
    .venv/
    *.sqlite
    .env.local
    storage/
''')


# ------------------------------------------------------------------- scaffold

def new_project(argv: list[str]) -> int:
    """Create a new pylar project directory."""
    if not argv:
        sys.stderr.write("Usage: pylar new <project-name>\\n")
        return 1

    name = argv[0]
    root = Path.cwd() / name

    if root.exists():
        sys.stderr.write(f"Directory '{name}' already exists.\\n")
        return 1

    # Directories
    dirs = [
        "app/http/controllers",
        "app/models",
        "app/providers",
        "app/observers",
        "app/policies",
        "config",
        "database/migrations",
        "database/seeds",
        "resources/views/layouts",
        "routes",
        "storage",
        "tests",
    ]
    for d in dirs:
        (root / d).mkdir(parents=True, exist_ok=True)

    # __init__.py files
    for pkg in [
        "app",
        "app/http",
        "app/http/controllers",
        "app/models",
        "app/providers",
        "app/observers",
        "app/policies",
        "config",
        "database",
        "database/seeds",
        "routes",
        "tests",
    ]:
        (root / pkg / "__init__.py").write_text("", encoding="utf-8")

    # Config
    _write(root / "config/app.py", _CONFIG_APP, name=name)
    _write(root / "config/database.py", _CONFIG_DATABASE, name=name)

    # Auth config + User model
    _copy_stub("auth_config.py.stub", root / "config/auth.py")
    _copy_stub("user_model.py.stub", root / "app/models/user.py")

    # Migrations — core system tables shipped by the framework.
    # Laravel ships an analogous bundle; every table here is required
    # by at least one framework feature (auth, queue driver, cache
    # driver, notifications channel). Projects that don't bind the
    # corresponding driver can delete the unused migration before the
    # first run.
    #
    # Stubs are shipped with canonical date prefixes that encode the
    # migration order (see Constitution rule IX.19). We copy them
    # verbatim — same filename, same ``Create Date`` header, same
    # revision header — so every project ends up with an identical
    # system-table chain regardless of *when* the project was
    # generated. Blog and dvozero then layer their own migrations
    # *after* the last stub revision (currently ``0009``).
    stubs_dir = Path(__file__).resolve().parent.parent / "auth" / "stubs"
    migrations_dir = root / "database/migrations"
    for stub in sorted(stubs_dir.glob("2026_*.py.stub")):
        target_name = stub.name.removesuffix(".stub")
        _copy_stub(stub.name, migrations_dir / target_name)

    # Providers
    _write(root / "app/providers/app_service_provider.py", _APP_PROVIDER, name=name)
    _write(root / "app/providers/route_service_provider.py", _ROUTE_PROVIDER, name=name)

    # Routes
    _write(root / "routes/web.py", _ROUTES_WEB, name=name)
    _write(root / "routes/api.py", _ROUTES_API, name=name)

    # Views
    _write(root / "resources/views/layouts/app.html", _LAYOUT, name=name)
    _write(root / "resources/views/home.html", _HOME, name=name)

    # Env + gitignore (generate fresh secrets for the new project)
    import secrets

    from pylar.encryption.encrypter import Encrypter

    _write(
        root / ".env",
        _ENV,
        name=name,
        app_key=Encrypter.generate_key(),
        session_secret=secrets.token_urlsafe(32),
    )
    _write(root / ".gitignore", _GITIGNORE, name=name)

    sys.stdout.write(
        f"Created project '{name}'.\n\n"
        f"  cd {name}\n"
        f"  pylar migrate\n"
        f"  pylar serve\n\n"
    )
    return 0


def _write(path: Path, template: str, **kwargs: str) -> None:
    """Write *template* to *path*, substituting ``${key}`` placeholders."""
    from string import Template

    content = Template(template).safe_substitute(**kwargs)
    path.write_text(content, encoding="utf-8")


def _copy_stub(stub_name: str, dest: Path, **kwargs: str) -> None:
    """Copy a stub from ``pylar/auth/stubs/`` to *dest*, substituting placeholders."""
    from string import Template

    stubs_dir = Path(__file__).resolve().parent.parent / "auth" / "stubs"
    source = stubs_dir / stub_name
    content = Template(source.read_text(encoding="utf-8")).safe_substitute(**kwargs)
    dest.write_text(content, encoding="utf-8")
