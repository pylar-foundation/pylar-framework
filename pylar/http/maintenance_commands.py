"""``pylar down`` / ``pylar up`` — toggle maintenance mode.

Both commands support two backends, matching
:class:`MaintenanceModeMiddleware`:

* **file** (default): creates / removes ``storage/framework/down``.
* **cache**: sets / deletes the ``pylar:maintenance:down`` key in the
  bound :class:`Cache`, so a single ``pylar down`` propagates to
  every node that shares the same cache backend.

Pass ``--driver cache`` to use the cache backend.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pylar.console.command import Command
from pylar.console.output import Output
from pylar.foundation.application import Application
from pylar.foundation.container import Container

_FLAG_RELATIVE = Path("storage/framework/down")
_CACHE_KEY = "pylar:maintenance:down"


def _flag_path(app: Application) -> Path:
    """Resolve the maintenance flag path relative to the project root."""
    return app.base_path / _FLAG_RELATIVE


@dataclass(frozen=True)
class _DownInput:
    driver: str = field(
        default="file",
        metadata={"help": "Backend: 'file' (default) or 'cache'"},
    )


class DownCommand(Command[_DownInput]):
    name = "down"
    description = "Put the application into maintenance mode"
    input_type = _DownInput

    def __init__(self, app: Application, container: Container, output: Output) -> None:
        self._app = app
        self._container = container
        self.out = output

    async def handle(self, input: _DownInput) -> int:
        if input.driver == "cache":
            from pylar.cache import Cache

            cache = self._container.make(Cache)
            await cache.put(_CACHE_KEY, "1")
        else:
            flag = _flag_path(self._app)
            flag.parent.mkdir(parents=True, exist_ok=True)
            flag.write_text("", encoding="utf-8")
        self.out.warn(
            f"Application is now in maintenance mode (driver={input.driver})."
        )
        return 0


@dataclass(frozen=True)
class _UpInput:
    driver: str = field(
        default="file",
        metadata={"help": "Backend: 'file' (default) or 'cache'"},
    )


class UpCommand(Command[_UpInput]):
    name = "up"
    description = "Bring the application out of maintenance mode"
    input_type = _UpInput

    def __init__(self, app: Application, container: Container, output: Output) -> None:
        self._app = app
        self._container = container
        self.out = output

    async def handle(self, input: _UpInput) -> int:
        if input.driver == "cache":
            from pylar.cache import Cache

            cache = self._container.make(Cache)
            await cache.forget(_CACHE_KEY)
        else:
            try:
                _flag_path(self._app).unlink()
            except FileNotFoundError:
                pass
        self.out.success("Application is now live.")
        return 0
