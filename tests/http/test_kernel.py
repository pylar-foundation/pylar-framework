"""Behavioural tests for :class:`pylar.http.HttpKernel`."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from pylar.foundation import AppConfig, Application
from pylar.http import HttpKernel, HttpServerConfig


def _make_app() -> Application:
    return Application(
        base_path=Path("/tmp/pylar-http-test"),
        config=AppConfig(name="http-test", debug=True, providers=()),
    )


def test_asgi_requires_bootstrapped_application() -> None:
    kernel = HttpKernel(_make_app())
    with pytest.raises(RuntimeError, match="bootstrapped Application"):
        kernel.asgi()


async def test_asgi_returns_starlette_app_after_bootstrap() -> None:
    app = _make_app()
    await app.bootstrap()
    kernel = HttpKernel(app)
    asgi = kernel.asgi()

    transport = httpx.ASGITransport(app=asgi)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/anything")
    # No routes registered yet — we expect a 404 from Starlette.
    assert response.status_code == 404


def test_default_server_config() -> None:
    kernel = HttpKernel(_make_app())
    assert kernel.server == HttpServerConfig()
    assert kernel.server.host == "127.0.0.1"
    assert kernel.server.port == 8000


def test_custom_server_config() -> None:
    kernel = HttpKernel(_make_app(), server=HttpServerConfig(host="0.0.0.0", port=9000))
    assert kernel.server.host == "0.0.0.0"
    assert kernel.server.port == 9000
