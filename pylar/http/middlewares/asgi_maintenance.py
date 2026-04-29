"""ASGI-level maintenance mode — short-circuits with 503 before routing.

The :class:`MaintenanceModeMiddleware` (route-pipeline variant) only
fires for matched routes. This ASGI counterpart is mounted on the
Starlette application itself by :class:`HttpKernel` so *every* request
— including 404s — gets an early 503 when the maintenance flag is
active. That is the behaviour Laravel users expect from
``php artisan down``: every URL returns the maintenance page until
``php artisan up``.

The middleware is auto-registered by :class:`HttpKernel` so applications
do not need to opt in. Override the flag location via subclassing or
disable entirely by removing the registration in a custom kernel.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send


class ASGIMaintenanceMiddleware:
    """Return 503 for every request when ``storage/framework/down`` exists.

    Two backends mirror :class:`MaintenanceModeMiddleware`:

    * ``backend="file"`` — checks ``flag_path`` on disk (default).
    * ``backend="cache"`` — checks ``cache_key`` in the bound cache.

    Constructor parameters override the defaults so the kernel can
    inject them from configuration::

        ASGIMaintenanceMiddleware(
            app, backend="cache", cache=cache, except_paths=("/health",)
        )
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        backend: str = "file",
        flag_path: str = "storage/framework/down",
        cache: Any = None,
        cache_key: str = "pylar:maintenance:down",
        retry_after: int = 60,
        except_paths: tuple[str, ...] = (),
        message: str = "Service Unavailable — back shortly.",
    ) -> None:
        self.app = app
        self._backend = backend
        self._flag_path = flag_path
        self._cache = cache
        self._cache_key = cache_key
        self._retry_after = retry_after
        self._except_paths = except_paths
        self._message = message

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "/")
        if any(path.startswith(prefix) for prefix in self._except_paths):
            await self.app(scope, receive, send)
            return

        if not await self._is_down():
            await self.app(scope, receive, send)
            return

        response = Response(
            content=self._message,
            status_code=503,
            headers={"Retry-After": str(self._retry_after)},
            media_type="text/plain",
        )
        await response(scope, receive, send)

    async def _is_down(self) -> bool:
        if self._backend == "cache":
            if self._cache is None:
                return False
            try:
                return bool(await self._cache.has(self._cache_key))
            except Exception:
                return False
        return Path(self._flag_path).exists()
