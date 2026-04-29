"""Tests for bundled HTTP middleware."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import httpx

from pylar.foundation import AppConfig, Application, Container, ServiceProvider
from pylar.http import (
    CorsMiddleware,
    HttpKernel,
    MaintenanceModeMiddleware,
    Request,
    RequestIdMiddleware,
    Response,
    SecureHeadersMiddleware,
    TrimStringsMiddleware,
    TrustProxiesMiddleware,
    json,
)
from pylar.routing import Router

# ----------------------------------------------------------- helpers


async def _echo(request: Request) -> Response:
    return json({
        "client": request.client.host if request.client else None,
        "scheme": request.url.scheme,
        "request_id": request.scope.get("request_id"),
    })


async def _echo_body(request: Request) -> Response:
    raw = request.scope.get("_body_override") or await request.body()
    return Response(content=raw, media_type="application/json")


async def _options_noop(request: Request) -> Response:
    return Response(status_code=204)


class _Routes(ServiceProvider):
    middlewares: ClassVar[list[type]] = []

    def register(self, container: Container) -> None:
        router = Router()
        group = router.group(middleware=self.middlewares)
        group.get("/echo", _echo)
        group.post("/echo", _echo_body)
        group.options("/echo", _options_noop)
        container.singleton(Router, lambda: router)


async def _make_client(
    middlewares: list[type], base_path: str = "/tmp/pylar-mw-test"
) -> tuple[Application, httpx.AsyncClient]:
    _Routes.middlewares = middlewares
    app = Application(
        base_path=Path(base_path),
        config=AppConfig(name="mw-test", debug=True, providers=(_Routes,)),
    )
    await app.bootstrap()
    transport = httpx.ASGITransport(app=HttpKernel(app).asgi())
    client = httpx.AsyncClient(transport=transport, base_url="http://test")
    return app, client


# ----------------------------------------------------------- CORS


async def test_cors_preflight_returns_204() -> None:
    app, client = await _make_client([CorsMiddleware])
    r = await client.options(
        "/echo",
        headers={
            "Origin": "https://spa.example.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert r.status_code == 204
    assert r.headers["access-control-allow-origin"] == "https://spa.example.com"
    assert "POST" in r.headers["access-control-allow-methods"]
    await app.shutdown()


async def test_cors_simple_request_adds_headers() -> None:
    app, client = await _make_client([CorsMiddleware])
    r = await client.get("/echo", headers={"Origin": "https://app.io"})
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "https://app.io"
    await app.shutdown()


async def test_cors_restricted_origin_blocks() -> None:
    class Strict(CorsMiddleware):
        allowed_origins = ("https://only-this.com",)

    app, client = await _make_client([Strict])
    r = await client.get("/echo", headers={"Origin": "https://evil.com"})
    assert "access-control-allow-origin" not in r.headers
    await app.shutdown()


# ------------------------------------------------------ TrustProxies


class _TrustAll(TrustProxiesMiddleware):
    """Test subclass that trusts all sources — mirrors the old default."""

    trusted_proxies = ("*",)


async def test_trust_proxies_patches_client_ip() -> None:
    app, client = await _make_client([_TrustAll])
    r = await client.get("/echo", headers={"X-Forwarded-For": "1.2.3.4, 10.0.0.1"})
    assert r.json()["client"] == "1.2.3.4"
    await app.shutdown()


async def test_trust_proxies_patches_scheme() -> None:
    app, client = await _make_client([_TrustAll])
    r = await client.get("/echo", headers={"X-Forwarded-Proto": "https"})
    assert r.json()["scheme"] == "https"
    await app.shutdown()


async def test_trust_proxies_default_trusts_nobody() -> None:
    """With the default empty tuple, forwarded headers are ignored."""
    app, client = await _make_client([TrustProxiesMiddleware])
    r = await client.get("/echo", headers={"X-Forwarded-For": "1.2.3.4"})
    # Client IP should NOT be patched — still the test transport's IP.
    assert r.json()["client"] != "1.2.3.4"
    await app.shutdown()


# ------------------------------------------------------- SecureHeaders


async def test_secure_headers_sets_defaults() -> None:
    app, client = await _make_client([SecureHeadersMiddleware])
    r = await client.get("/echo")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "max-age=31536000" in r.headers["strict-transport-security"]
    await app.shutdown()


# --------------------------------------------------------- RequestId


async def test_request_id_generated_when_missing() -> None:
    app, client = await _make_client([RequestIdMiddleware])
    r = await client.get("/echo")
    assert "x-request-id" in r.headers
    assert r.json()["request_id"] == r.headers["x-request-id"]
    await app.shutdown()


async def test_request_id_propagated_from_header() -> None:
    app, client = await _make_client([RequestIdMiddleware])
    r = await client.get("/echo", headers={"X-Request-Id": "my-trace-42"})
    assert r.headers["x-request-id"] == "my-trace-42"
    assert r.json()["request_id"] == "my-trace-42"
    await app.shutdown()


# ------------------------------------------------- MaintenanceMode


async def test_maintenance_mode_returns_503(tmp_path: Path) -> None:
    flag = tmp_path / "down"

    class TestMaintenance(MaintenanceModeMiddleware):
        flag_path = str(flag)
        except_paths = ("/health",)

    app, client = await _make_client([TestMaintenance], str(tmp_path))
    await app.bootstrap()

    # Normal mode.
    r = await client.get("/echo")
    assert r.status_code == 200

    # Down.
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text("")
    r = await client.get("/echo")
    assert r.status_code == 503
    assert r.headers["retry-after"] == "60"

    # Up.
    flag.unlink()
    r = await client.get("/echo")
    assert r.status_code == 200
    await app.shutdown()


async def test_maintenance_mode_excepts_paths(tmp_path: Path) -> None:
    flag = tmp_path / "down"
    flag.write_text("")

    class TestMaintenance(MaintenanceModeMiddleware):
        flag_path = str(flag)
        except_paths = ("/echo",)

    app, client = await _make_client([TestMaintenance], str(tmp_path))
    r = await client.get("/echo")
    assert r.status_code == 200  # excepted path bypasses 503
    await app.shutdown()


# -------------------------------------------------------- TrimStrings


async def test_trim_strings_strips_json_values() -> None:
    app, client = await _make_client([TrimStringsMiddleware])
    r = await client.post(
        "/echo",
        content='{"name": "  Alice  ", "email": " a@b "}',
        headers={"Content-Type": "application/json"},
    )
    import json as _json
    body = _json.loads(r.content)
    assert body["name"] == "Alice"
    assert body["email"] == "a@b"
    await app.shutdown()


async def test_trim_strings_skips_password() -> None:
    app, client = await _make_client([TrimStringsMiddleware])
    r = await client.post(
        "/echo",
        content='{"password": "  secret  "}',
        headers={"Content-Type": "application/json"},
    )
    import json as _json
    body = _json.loads(r.content)
    assert body["password"] == "  secret  "
    await app.shutdown()
