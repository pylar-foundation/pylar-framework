"""Tests for the centralised error handler."""

from __future__ import annotations

from pathlib import Path

import httpx

from pylar.foundation import AppConfig, Application, Container, ServiceProvider
from pylar.http import HttpKernel, NotFound, Request, Response, json
from pylar.routing import Router


async def _boom(request: Request) -> Response:
    raise RuntimeError("something broke")


async def _not_found(request: Request) -> Response:
    raise NotFound("gone")


async def _ok(request: Request) -> Response:
    return json({"ok": True})


class _Routes(ServiceProvider):
    def register(self, container: Container) -> None:
        router = Router()
        router.get("/boom", _boom)
        router.get("/missing", _not_found)
        router.get("/ok", _ok)
        container.singleton(Router, lambda: router)


async def _client(debug: bool) -> tuple[Application, httpx.AsyncClient]:
    app = Application(
        base_path=Path("/tmp/pylar-err-test"),
        config=AppConfig(name="err-test", debug=debug, providers=(_Routes,)),
    )
    await app.bootstrap()
    transport = httpx.ASGITransport(
        app=HttpKernel(app).asgi(), raise_app_exceptions=False
    )
    return app, httpx.AsyncClient(transport=transport, base_url="http://test")


# ------------------------------------------------------ debug mode


async def test_debug_500_shows_traceback() -> None:
    app, c = await _client(debug=True)
    r = await c.get("/boom")
    assert r.status_code == 500
    assert "RuntimeError" in r.text
    assert "something broke" in r.text
    assert "test_error_handler" in r.text  # file appears in traceback
    assert "<html" in r.text
    await app.shutdown()


async def test_debug_404_shows_detail() -> None:
    app, c = await _client(debug=True)
    r = await c.get("/missing")
    assert r.status_code == 404
    assert "gone" in r.text
    await app.shutdown()


# ------------------------------------------------- production mode


_JSON = {"accept": "application/json"}


async def test_production_500_hides_details() -> None:
    app, c = await _client(debug=False)
    r = await c.get("/boom", headers=_JSON)
    assert r.status_code == 500
    body = r.json()
    assert body["message"] == "Internal Server Error"
    assert body["code"] == 500
    assert "trace" not in body  # no trace in production
    assert "RuntimeError" not in r.text
    assert "something broke" not in r.text
    await app.shutdown()


async def test_production_404_generic() -> None:
    app, c = await _client(debug=False)
    r = await c.get("/missing", headers=_JSON)
    assert r.status_code == 404
    body = r.json()
    assert body["code"] == 404
    assert "message" in body
    assert "trace" not in body
    await app.shutdown()


async def test_production_unknown_route_404() -> None:
    app, c = await _client(debug=False)
    r = await c.get("/no-such-route", headers=_JSON)
    assert r.status_code == 404
    body = r.json()
    assert body["code"] == 404
    assert "message" in body
    assert "trace" not in body
    await app.shutdown()


async def test_production_html_404_serves_builtin_page() -> None:
    """Browser clients in production see the built-in HTML page, not JSON."""
    app, c = await _client(debug=False)
    r = await c.get("/missing", headers={"accept": "text/html"})
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("text/html")
    assert "<html" in r.text
    assert "404" in r.text
    assert "Page Not Found" in r.text
    # Plain-text exception message never leaks to the browser page.
    assert "trace" not in r.text.lower()
    await app.shutdown()


async def test_production_html_500_serves_builtin_page() -> None:
    app, c = await _client(debug=False)
    r = await c.get("/boom", headers={"accept": "text/html"})
    assert r.status_code == 500
    assert r.headers["content-type"].startswith("text/html")
    assert "<html" in r.text
    assert "500" in r.text
    assert "Server Error" in r.text
    assert "RuntimeError" not in r.text
    await app.shutdown()


async def test_register_error_page_overrides_builtin() -> None:
    from starlette.responses import HTMLResponse

    from pylar.http import register_error_page
    from pylar.http.error_pages import clear_custom_error_pages

    clear_custom_error_pages()

    async def _custom_404(request: Request, status: int) -> Response:
        return HTMLResponse("<h1>custom 404</h1>", status_code=status)

    register_error_page(404, _custom_404)
    try:
        app, c = await _client(debug=False)
        r = await c.get("/missing", headers={"accept": "text/html"})
        assert r.status_code == 404
        assert r.text == "<h1>custom 404</h1>"
        await app.shutdown()
    finally:
        clear_custom_error_pages()


async def test_debug_json_includes_trace() -> None:
    app, c = await _client(debug=True)
    r = await c.get("/boom", headers={"accept": "application/json"})
    assert r.status_code == 500
    body = r.json()
    assert body["message"] == "Internal Server Error"
    assert body["code"] == 500
    assert "trace" in body
    assert isinstance(body["trace"], list)
    assert any("something broke" in line for line in body["trace"])
    await app.shutdown()
