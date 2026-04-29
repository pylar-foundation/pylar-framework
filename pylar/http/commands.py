"""Console commands shipped by the HTTP layer."""

from __future__ import annotations

from dataclasses import dataclass, field

from pylar.console.command import Command
from pylar.console.output import Output
from pylar.foundation.application import Application


@dataclass(frozen=True)
class ServeInput:
    host: str = field(default="127.0.0.1", metadata={"help": "Address to bind"})
    port: int = field(default=8000, metadata={"help": "Port to bind"})
    log_level: str = field(default="info", metadata={"help": "uvicorn log level"})


class ServeCommand(Command[ServeInput]):
    """``pylar serve`` — bootstraps the application and runs it via uvicorn.

    Requires the ``pylar[serve]`` extra so that uvicorn is importable.
    The HTTP kernel handles the actual lifecycle: it builds the
    Starlette ASGI app from the bootstrapped application and hands it
    to uvicorn's :class:`Server` until the process is interrupted.
    """

    name = "serve"
    description = "Run the application's HTTP server via uvicorn"
    input_type = ServeInput

    def __init__(self, app: Application, output: Output) -> None:
        self._app = app
        self.out = output

    async def handle(self, input: ServeInput) -> int:
        # Local import — the http kernel pulls in starlette eagerly
        # which is fine, but importing it from the command module would
        # create a cycle through pylar.http.__init__.
        from pylar.http.kernel import HttpKernel, HttpServerConfig

        kernel = HttpKernel(
            self._app,
            server=HttpServerConfig(
                host=input.host,
                port=input.port,
                log_level=input.log_level,
            ),
        )
        self.out.info(
            f"Serving on http://{input.host}:{input.port} (Ctrl+C to stop)"
        )
        return await kernel.handle()


@dataclass(frozen=True)
class DevInput:
    host: str = field(default="127.0.0.1", metadata={"help": "Address to bind"})
    port: int = field(default=8000, metadata={"help": "Port to bind"})


class DevCommand(Command[DevInput]):
    """``pylar dev`` — start the server with auto-reload on code changes.

    Launches uvicorn with ``--reload`` enabled so file modifications
    in the project directory restart the server automatically. Meant
    for local development; ``pylar serve`` is the production-facing
    variant.
    """

    name = "dev"
    description = "Run the development server with auto-reload"
    input_type = DevInput

    def __init__(self, app: Application, output: Output) -> None:
        self._app = app
        self.out = output

    async def handle(self, input: DevInput) -> int:
        import asyncio
        import sys

        try:
            import uvicorn  # noqa: F401
        except ImportError:
            self.out.error(
                "pylar dev requires uvicorn. Install with: pip install 'pylar[serve]'"
            )
            return 1

        self.out.info(
            f"[dev] http://{input.host}:{input.port} — auto-reload enabled"
        )

        # Uvicorn reload spawns child processes that re-import the app.
        # We run it as a subprocess so the reload watcher controls the
        # lifecycle cleanly — the async event loop stays out of the way.
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "uvicorn",
            "pylar.http.kernel:create_asgi_app",
            "--factory",
            "--host", input.host,
            "--port", str(input.port),
            "--reload",
            "--log-level", "info",
        )
        await proc.wait()
        return proc.returncode or 0
