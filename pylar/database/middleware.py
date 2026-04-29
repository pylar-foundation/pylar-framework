"""HTTP middleware that opens a database session for each request."""

from __future__ import annotations

from pylar.database.connection import ConnectionManager
from pylar.database.session import use_session
from pylar.http.middleware import RequestHandler
from pylar.http.request import Request
from pylar.http.response import Response


class DatabaseSessionMiddleware:
    """Wraps every request in :func:`use_session`.

    Once this middleware runs, controllers and services can call
    :func:`pylar.database.current_session` (or any :class:`Manager` /
    :class:`QuerySet` terminal method that uses it implicitly) without
    having to thread the session through their own arguments.

    The middleware **does not commit on its own** — write paths are expected
    to use :func:`pylar.database.transaction` to make their commit boundary
    explicit. Implicit commit-on-2xx is intentionally avoided because it
    masks failures and turns reads into writes.
    """

    def __init__(self, manager: ConnectionManager) -> None:
        self._manager = manager

    async def handle(self, request: Request, next_handler: RequestHandler) -> Response:
        async with use_session(self._manager):
            return await next_handler(request)
