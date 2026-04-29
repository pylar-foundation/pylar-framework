"""``pylar tinker`` — interactive REPL with the application bootstrapped.

Boots the full application (container, providers, database connection),
pre-imports all registered models, and drops into an async-capable REPL.

Uses IPython when available (recommended — supports ``await`` natively
in the REPL).  Falls back to the stdlib ``code.interact`` when IPython
is not installed, wrapping async calls with ``asyncio.run()``.

Install IPython for the best experience::

    pip install 'pylar[tinker]'
    # or
    pip install ipython
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any, cast

from pylar.console.command import Command
from pylar.database.model import Model
from pylar.foundation.application import Application
from pylar.foundation.container import Container


@dataclass(frozen=True)
class TinkerInput:
    """No arguments — opens an interactive shell."""


class TinkerCommand(Command[TinkerInput]):
    """Open an interactive shell with the application context loaded.

    The REPL namespace includes:

    * ``app`` — the bootstrapped :class:`Application` instance.
    * ``container`` — the IoC container (``container.make(Type)``).
    * Every concrete :class:`Model` subclass discovered during bootstrap.
    * Common framework imports (``Q``, ``F``, ``transaction``, etc.).

    With IPython you can ``await`` directly in the REPL::

        >>> posts = await Post.query.all()
        >>> await Post.query.count()
        55
    """

    name = "tinker"
    description = "Open an interactive shell with the application context"
    input_type = TinkerInput

    def __init__(self, app: Application, container: Container) -> None:
        self._app = app
        self._container = container

    async def handle(self, input: TinkerInput) -> int:
        namespace = self._build_namespace()

        # Open an ambient database session so ORM queries work
        # directly in the REPL without manual use_session() wrappers.
        session, token = await self._open_session(namespace)

        banner = self._build_banner(namespace)

        try:
            return self._start_ipython(namespace, banner)
        except ImportError:
            return self._start_stdlib(namespace, banner)
        finally:
            if session is not None:
                try:
                    await session.close()
                except Exception:
                    pass
            if token is not None:
                from pylar.database.session import _current_session

                _current_session.reset(token)

    async def _open_session(
        self, namespace: dict[str, Any]
    ) -> tuple[Any, Any]:
        """Open an ambient DB session and set the context variable directly.

        Returns ``(session, token)`` for cleanup. The session stays open
        for the entire REPL lifetime — using a plain ``ContextVar.set``
        instead of ``async with use_session`` means the value survives
        across IPython's autoawait-spawned tasks, which otherwise run
        in a context where the var was never set.
        """
        try:
            from pylar.database.connection import ConnectionManager
            from pylar.database.session import _current_session

            manager = self._container.make(ConnectionManager)
            session = manager.session()
            token = _current_session.set(session)
            namespace["session"] = session
            return session, token
        except Exception:
            return None, None

    def _build_namespace(self) -> dict[str, Any]:
        """Collect models, services, and helpers into a REPL namespace."""
        ns: dict[str, Any] = {
            "app": self._app,
            "container": self._container,
        }

        # Eagerly import every module under app/models/ so that
        # __subclasses__() picks up models no provider imported yet.
        base_path = getattr(self._app, "base_path", None)
        if base_path is not None:
            _import_app_models(base_path)

        # Import all concrete Model subclasses that have a table.
        for model_cls in _discover_models():
            ns[model_cls.__name__] = model_cls

        # Common framework utilities.
        _safe_import(ns, "pylar.database", ["transaction", "use_session", "current_session"])
        _safe_import(ns, "pylar.database.expressions", ["Q", "F"])
        _safe_import(ns, "pylar.auth", ["current_user", "current_user_or_none", "Gate"])
        _safe_import(ns, "pylar.cache", ["Cache"])
        _safe_import(ns, "pylar.events", ["EventBus"])
        _safe_import(ns, "pylar.http", ["Request", "Response", "JsonResponse"])

        # Try to resolve key singletons from the container.
        for type_name in ("Gate", "Cache", "EventBus"):
            cls = ns.get(type_name)
            if cls is not None:
                try:
                    instance = self._container.make(cls)
                    # Lowercase alias: gate, cache, event_bus.
                    alias = type_name[0].lower() + type_name[1:]
                    alias = "".join(
                        f"_{c.lower()}" if c.isupper() else c for c in alias
                    )
                    ns[alias] = instance
                except Exception:
                    pass

        return ns

    def _build_banner(self, namespace: dict[str, Any]) -> str:
        """Build the REPL welcome banner."""
        model_names = sorted(
            name for name, obj in namespace.items()
            if isinstance(obj, type) and issubclass(obj, Model) and obj is not Model
        )
        lines = [
            f"Pylar Tinker (v{self._app.config.name})",
            "",
            "Available in namespace:",
            "  app, container",
        ]
        if model_names:
            lines.append(f"  Models: {', '.join(model_names)}")

        extras = []
        for key in ("session", "gate", "cache", "event_bus", "transaction", "Q", "F"):
            if key in namespace:
                extras.append(key)
        if extras:
            lines.append(f"  Helpers: {', '.join(extras)}")

        lines.append("")
        lines.append("Use `await` for async operations (IPython).")
        lines.append("Type `exit()` or Ctrl-D to quit.")
        lines.append("")
        return "\n".join(lines)

    def _start_ipython(self, namespace: dict[str, Any], banner: str) -> int:
        """Launch IPython with autoawait enabled.

        pylar commands run inside ``asyncio.run()``, so there is already
        a running event loop. IPython / prompt_toolkit will try to call
        ``asyncio.run()`` again which raises ``RuntimeError``. We patch
        the loop with ``nest_asyncio`` (bundled with IPython >= 8) so
        nested ``run()`` calls succeed.
        """
        import asyncio

        try:
            import nest_asyncio
        except ImportError:
            # nest_asyncio ships with IPython >= 8 as a dependency; if
            # it is somehow missing, install it: pip install nest_asyncio
            raise ImportError(
                "nest_asyncio is required for tinker with IPython. "
                "Install with: pip install nest_asyncio"
            ) from None

        nest_asyncio.apply(asyncio.get_event_loop())

        from IPython.terminal.embed import InteractiveShellEmbed

        shell = cast(Any, InteractiveShellEmbed)(
            user_ns=namespace,
            banner1=banner,
        )
        # Enable autoawait so `await Model.query.all()` works directly.
        shell.run_line_magic("autoawait", "True")
        shell()
        return 0

    def _start_stdlib(self, namespace: dict[str, Any], banner: str) -> int:
        """Fallback: use stdlib code.interact."""
        import code

        banner += (
            "\nNote: IPython is not installed. `await` won't work directly.\n"
            "Use `import asyncio; asyncio.run(Post.query.count())` instead.\n"
            "Install IPython for async support: pip install ipython\n\n"
        )
        code.interact(banner=banner, local=namespace)
        return 0


def _discover_models() -> list[type[Model]]:
    """Return all concrete Model subclasses that have been imported so far.

    After Application.bootstrap() runs, all providers have booted and
    models referenced by the app are already in Python's class registry.
    We walk Model.__subclasses__() recursively to find them.
    """
    result: list[type[Model]] = []
    _walk_subclasses(Model, result)
    return result


def _walk_subclasses(base: type[Model], acc: list[type[Model]]) -> None:
    """Recursively collect non-abstract subclasses."""
    for cls in base.__subclasses__():
        if not getattr(cls, "__abstract__", False) and hasattr(cls, "__tablename__"):
            acc.append(cls)
        _walk_subclasses(cls, acc)


def _import_app_models(base_path: Any) -> None:
    """Import every ``*.py`` under ``app/models/`` so all Model subclasses register.

    After bootstrap most models are already imported by providers, but
    some (like a User model only referenced in config strings) may not
    be in ``__subclasses__()`` yet. This scan ensures tinker sees them.
    """
    from pathlib import Path

    models_dir = Path(str(base_path)) / "app" / "models"
    if not models_dir.is_dir():
        return
    for py_file in sorted(models_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        module_name = f"app.models.{py_file.stem}"
        try:
            importlib.import_module(module_name)
        except Exception:
            pass


def _safe_import(ns: dict[str, Any], module_path: str, names: list[str]) -> None:
    """Import *names* from *module_path* into *ns*, silently skipping failures."""
    try:
        module = importlib.import_module(module_path)
        for name in names:
            obj = getattr(module, name, None)
            if obj is not None:
                ns[name] = obj
    except ImportError:
        pass
