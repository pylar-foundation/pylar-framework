"""``pylar`` script entry point.

When the user runs ``pylar make:model User`` (or ``./pylar`` inside a project)
this is the function that ``pyproject.toml`` dispatches to. It locates the
project's :class:`AppConfig`, constructs an :class:`Application`, and runs the
:class:`ConsoleKernel`.

The function is intentionally tiny — it owns process boundary concerns
(``sys.argv``, ``sys.path``, exit codes) and nothing else.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path

from pylar.console.kernel import ConsoleKernel
from pylar.foundation.application import AppConfig, Application


def main() -> int:
    # `pylar new <name>` runs outside any project — handle it before
    # trying to load config/app.py which would not exist yet.
    if len(sys.argv) >= 2 and sys.argv[1] == "new":
        from pylar.console.new_project import new_project

        return new_project(sys.argv[2:])

    base_path = Path.cwd()
    if str(base_path) not in sys.path:
        sys.path.insert(0, str(base_path))

    # Load .env from the project root (if it exists) so env vars are
    # available before config/app.py is imported.
    from pylar.config.env import load_dotenv

    load_dotenv(base_path / ".env")

    config = _load_app_config()
    app = Application(base_path=base_path, config=config)
    kernel = ConsoleKernel(app=app, argv=sys.argv[1:])
    return asyncio.run(app.run(kernel))


def _load_app_config() -> AppConfig:
    """Import ``config.app`` from the current project and return its ``config``."""
    try:
        module = importlib.import_module("config.app")
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "Could not import `config.app` from the current directory. "
            "Run pylar from the root of a project that has a `config/app.py` file."
        ) from exc

    config = getattr(module, "config", None)
    if not isinstance(config, AppConfig):
        raise SystemExit(
            "config/app.py must export `config = AppConfig(...)` to be runnable by pylar."
        )
    return config


if __name__ == "__main__":  # pragma: no cover - exercised by integration tests only
    raise SystemExit(main())
