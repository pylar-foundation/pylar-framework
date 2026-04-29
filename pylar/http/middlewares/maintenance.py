"""Return 503 when the application is in maintenance mode.

The maintenance flag can be stored in two ways:

* **File** (default) — a flag file on disk at :attr:`flag_path`.
  ``pylar down`` creates it, ``pylar up`` removes it. Zero deps.
* **Cache** — a key in the bound :class:`pylar.cache.Cache`.
  Useful in multi-instance deployments where a shared Redis (or
  database) cache lets ``pylar down`` take down every node at once
  without shared filesystem access.

Set :attr:`backend` to ``"cache"`` to switch. The file backend is
the default because it works everywhere without extra infrastructure.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Literal

from pylar.http.middleware import RequestHandler
from pylar.http.request import Request
from pylar.http.response import Response

if TYPE_CHECKING:
    from pylar.cache import Cache


class MaintenanceModeMiddleware:
    """Short-circuit with 503 when the maintenance flag is active.

    Configuration via subclass attributes::

        class AppMaintenance(MaintenanceModeMiddleware):
            backend = "cache"
            cache_key = "app:down"
            except_paths = ("/health",)

    When ``backend="cache"`` the middleware receives a :class:`Cache`
    through its ``__init__`` (auto-wired by the container). When
    ``backend="file"`` no extra dependencies are needed.
    """

    #: ``"file"`` checks a flag file; ``"cache"`` checks a cache key.
    backend: ClassVar[Literal["file", "cache"]] = "file"

    #: Path to the flag file (file backend only).
    flag_path: ClassVar[str] = "storage/framework/down"

    #: Cache key for the maintenance flag (cache backend only).
    cache_key: ClassVar[str] = "pylar:maintenance:down"

    #: Seconds the client should wait before retrying.
    retry_after: ClassVar[int] = 60

    #: URL path prefixes that bypass maintenance mode.
    except_paths: ClassVar[tuple[str, ...]] = ()

    #: Response body served during maintenance.
    message: ClassVar[str] = "Service Unavailable — back shortly."

    def __init__(self, cache: Cache | None = None) -> None:
        self._cache = cache

    async def handle(
        self, request: Request, next_handler: RequestHandler
    ) -> Response:
        if not await self._is_down():
            return await next_handler(request)
        if self._is_excepted(request):
            return await next_handler(request)
        return Response(
            content=self.message,
            status_code=503,
            headers={"Retry-After": str(self.retry_after)},
            media_type="text/plain",
        )

    async def _is_down(self) -> bool:
        if self.backend == "cache":
            if self._cache is None:
                return False
            return await self._cache.has(self.cache_key)
        return Path(self.flag_path).exists()

    def _is_excepted(self, request: Request) -> bool:
        path = request.url.path
        return any(path.startswith(prefix) for prefix in self.except_paths)
