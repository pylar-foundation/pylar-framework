"""HTTP kernel — bridges :class:`Application` to a Starlette ASGI app.

The kernel exposes two complementary entry points:

* :meth:`HttpKernel.asgi` — synchronously builds and returns the ASGI
  callable. This is what tests, third-party servers, and ``uvicorn`` import.
* :meth:`HttpKernel.handle` — implements :class:`pylar.foundation.Kernel` and
  runs uvicorn until the process exits. uvicorn is an optional dependency,
  installed via the ``pylar[serve]`` extra.

The kernel does not yet know about routing or middleware: those are wired in
by the routing module in the next iteration. For now it produces an empty
Starlette app whose only purpose is to demonstrate the bridge and exercise
the lifecycle in tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from starlette.applications import Starlette
from starlette.routing import BaseRoute

from pylar.foundation.application import Application


@dataclass(frozen=True, slots=True)
class HttpServerConfig:
    """Bind address for :meth:`HttpKernel.handle`."""

    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "info"


class HttpKernel:
    """Run an :class:`Application` as an HTTP service."""

    def __init__(
        self,
        app: Application,
        *,
        server: HttpServerConfig | None = None,
    ) -> None:
        self.app = app
        self.server = server if server is not None else HttpServerConfig()

    def asgi(self) -> Starlette:
        """Build the Starlette ASGI app for the bootstrapped pylar application.

        The pylar application **must** be bootstrapped before this is called,
        because routes and middleware are populated by service providers
        during boot.
        """
        if not self.app.is_booted:
            raise RuntimeError(
                "HttpKernel.asgi() requires a bootstrapped Application — "
                "call `await application.bootstrap()` first."
            )

        from pylar.http.error_handler import make_error_handlers

        routes: list[BaseRoute] = self._collect_routes()
        asgi_middleware = self._collect_asgi_middleware()
        # Pass debug=False to Starlette so its ServerErrorMiddleware
        # delegates to our handler instead of rendering its own plain
        # traceback. Our handler checks the app's debug flag internally
        # and renders a rich HTML page or a generic JSON response.
        return Starlette(
            debug=False,
            routes=routes,
            exception_handlers=make_error_handlers(
                self.app.config.debug, self.app.container,
            ),
            middleware=asgi_middleware,
        )

    def _collect_asgi_middleware(self) -> list[Any]:
        """Build the ASGI-level middleware stack.

        Order matters — middleware is applied outside-in. We mount:

        1. :class:`ASGIMaintenanceMiddleware` first so ``pylar down``
           short-circuits with 503 before any other work happens.
        2. :class:`ASGIThrottleMiddleware` next when a :class:`Cache`
           is bound, so DDoS traffic is rejected before routing.
        """
        from starlette.middleware import Middleware as StarletteMiddleware

        from pylar.http.middlewares.asgi_maintenance import ASGIMaintenanceMiddleware
        from pylar.http.middlewares.asgi_throttle import ASGIThrottleMiddleware
        from pylar.http.middlewares.max_body import MaxBodySizeMiddleware

        stack: list[StarletteMiddleware] = []

        # Maintenance mode: outermost layer, intercepts everything.
        # Flag path is anchored at base_path so it resolves the same
        # whether the user runs ``pylar down`` from the project root
        # or anywhere else under it.
        flag_path = str(self.app.base_path / "storage" / "framework" / "down")
        stack.append(
            StarletteMiddleware(
                ASGIMaintenanceMiddleware,
                flag_path=flag_path,
            )
        )

        # Body size limit: reject oversized payloads before routing.
        stack.append(StarletteMiddleware(MaxBodySizeMiddleware))

        try:
            from pylar.cache import Cache

            if self.app.container.has(Cache):
                cache = self.app.container.make(Cache)
                # Pull the session cookie name from SessionConfig if it
                # is bound — the throttle uses that cookie as one of
                # two "likely authenticated" signals, so mis-detecting
                # a rotated cookie name would silently demote every
                # signed-in user to the anon bucket.
                session_cookie = self._session_cookie_name()
                stack.append(
                    StarletteMiddleware(
                        ASGIThrottleMiddleware,
                        cache=cache,
                        container=self.app.container,
                        session_cookie=session_cookie,
                    )
                )
        except ImportError:
            pass
        return stack

    def _session_cookie_name(self) -> str:
        """Resolve the session cookie name via SessionConfig if bound."""
        try:
            from pylar.session.config import SessionConfig
        except ImportError:
            return "pylar_session_id"
        if not self.app.container.has(SessionConfig):
            return "pylar_session_id"
        return self.app.container.make(SessionConfig).cookie_name

    def _collect_routes(self) -> list[BaseRoute]:
        """Return the Starlette routes registered by the routing layer.

        If a :class:`pylar.routing.Router` is bound in the container — typically
        by the user's ``RouteServiceProvider`` — its routes are compiled into
        Starlette routes. Otherwise the kernel runs with no routes, producing
        a 404 for every path.
        """
        # Local import: pylar.routing depends on pylar.http, so we cannot import
        # it at module load time without creating a cycle.
        from pylar.routing import Router, RoutesCompiler

        if not self.app.container.has(Router):
            return []
        router = self.app.container.make(Router)
        return RoutesCompiler(self.app.container).compile(router)

    async def handle(self) -> int:
        """Bootstrap (if needed) and run uvicorn until shutdown."""
        await self.app.bootstrap()
        try:
            import uvicorn
        except ImportError as exc:  # pragma: no cover - exercised by docs only
            raise RuntimeError(
                "uvicorn is not installed. Install pylar with the 'serve' extra: "
                "pip install 'pylar[serve]'."
            ) from exc

        config = uvicorn.Config(
            app=self.asgi(),
            host=self.server.host,
            port=self.server.port,
            log_level=self.server.log_level,
            lifespan="off",  # pylar manages lifecycle itself
        )
        server = uvicorn.Server(config)
        await server.serve()
        return 0


def create_asgi_app() -> Starlette:
    """Factory callable for ``uvicorn --factory`` / ``pylar dev``.

    Builds an :class:`Application` from the project's ``config/app.py``,
    bootstraps it synchronously (safe — uvicorn calls the factory
    before entering the async loop), and returns the Starlette ASGI
    app. Used by :class:`DevCommand` so ``--reload`` reimports a
    fresh app on every file change.
    """
    import asyncio

    app = Application.from_config()
    asyncio.get_event_loop().run_until_complete(app.bootstrap())
    kernel = HttpKernel(app)
    return kernel.asgi()
