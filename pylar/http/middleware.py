"""Laravel-style HTTP middleware: ``handle(request, next) -> response``.

Pylar's middleware is intentionally a thin Protocol rather than an ASGI
middleware: it operates on already-parsed :class:`Request` objects and returns
a :class:`Response`. ASGI-level concerns (compression, CORS preflight, etc.)
are still handled by Starlette middleware mounted by the kernel — but the
domain-level pipeline that controllers see uses this protocol.

The :class:`Pipeline` helper composes a list of middleware around a final
handler in the same order Laravel does: the first middleware in the list runs
its pre-logic first and its post-logic last.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol, runtime_checkable

from pylar.http.request import Request
from pylar.http.response import Response

#: A callable that turns a request into a response. Used as the ``next``
#: argument passed to :meth:`Middleware.handle`.
RequestHandler = Callable[[Request], Awaitable[Response]]


@runtime_checkable
class Middleware(Protocol):
    """A typed HTTP middleware.

    Implementations receive the incoming request and a callable representing
    the rest of the pipeline. They must either return a response directly
    (short-circuiting the pipeline) or ``await next_handler(request)`` to
    delegate to the downstream handler and possibly modify its response.
    """

    async def handle(self, request: Request, next_handler: RequestHandler) -> Response: ...


class Pipeline:
    """Compose a sequence of :class:`Middleware` around a final handler."""

    def __init__(self, middlewares: Sequence[Middleware]) -> None:
        self._middlewares = tuple(middlewares)

    async def send(self, request: Request, finalizer: RequestHandler) -> Response:
        """Drive *request* through the pipeline and into *finalizer*.

        Middlewares run in declaration order on the way in and in reverse on
        the way out, exactly like Laravel's ``Pipeline::send``.
        """
        handler: RequestHandler = finalizer
        for middleware in reversed(self._middlewares):
            handler = self._wrap(middleware, handler)
        return await handler(request)

    @staticmethod
    def _wrap(middleware: Middleware, next_handler: RequestHandler) -> RequestHandler:
        async def wrapped(request: Request) -> Response:
            return await middleware.handle(request, next_handler)

        return wrapped
