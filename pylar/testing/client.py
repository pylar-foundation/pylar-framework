"""HTTP test client built on :class:`httpx.AsyncClient`.

The client wraps Starlette's :class:`ASGITransport` so tests drive the
fully-bootstrapped pylar :class:`HttpKernel` without spinning up an
external web server. The async context manager handles the kernel
build, transport lifetime, and graceful application shutdown.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx

from pylar.foundation import Application
from pylar.http import HttpKernel


@asynccontextmanager
async def http_client(
    app: Application,
    *,
    base_url: str = "http://test",
) -> AsyncIterator[httpx.AsyncClient]:
    """Yield a typed :class:`httpx.AsyncClient` bound to *app*'s ASGI surface.

    Bootstraps the application on enter and shuts it down on exit, so
    each test is responsible for nothing more than the request /
    assertion pair. The function is named ``http_client`` (not
    ``test_client``) to avoid pytest's collection of any helper whose
    name starts with ``test_``.
    """
    await app.bootstrap()
    kernel = HttpKernel(app)
    transport = httpx.ASGITransport(app=kernel.asgi())
    try:
        async with httpx.AsyncClient(transport=transport, base_url=base_url) as client:
            yield client
    finally:
        await app.shutdown()
