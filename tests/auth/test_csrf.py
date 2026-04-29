"""End-to-end tests for :class:`CsrfMiddleware` (double-submit cookie)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from pylar.auth import CsrfMiddleware
from pylar.foundation import (
    AppConfig,
    Application,
    Container,
    ServiceProvider,
)
from pylar.http import HttpKernel, Request, Response, json
from pylar.routing import Router


async def _ping(request: Request) -> Response:
    return json({"ok": True})


async def _bump(request: Request) -> Response:
    return json({"bumped": True})


class _RouteProvider(ServiceProvider):
    def register(self, container: Container) -> None:
        router = Router()
        protected = router.group(middleware=[CsrfMiddleware])
        protected.get("/ping", _ping)
        protected.post("/bump", _bump)
        protected.put("/bump/{id:int}", _bump)
        protected.delete("/bump/{id:int}", _bump)
        container.singleton(Router, lambda: router)


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = Application(
        base_path=Path("/tmp/pylar-csrf-test"),
        config=AppConfig(
            name="csrf-test",
            debug=True,
            providers=(_RouteProvider,),
        ),
    )
    await app.bootstrap()
    transport = httpx.ASGITransport(app=HttpKernel(app).asgi())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await app.shutdown()


# ----------------------------------------------------------- safe methods


async def test_get_sets_cookie_when_missing(client: httpx.AsyncClient) -> None:
    response = await client.get("/ping")
    assert response.status_code == 200
    assert "pylar_csrf" in response.cookies
    token = response.cookies["pylar_csrf"]
    assert len(token) > 20  # url-safe base64 of 32 bytes


async def test_get_does_not_overwrite_existing_cookie(
    client: httpx.AsyncClient,
) -> None:
    first = await client.get("/ping")
    token = first.cookies["pylar_csrf"]
    # Second request carries the cookie back; the middleware should
    # see it and skip the set-cookie header.
    second = await client.get("/ping", cookies={"pylar_csrf": token})
    assert "pylar_csrf" not in second.cookies  # no Set-Cookie this time


# ---------------------------------------------------------- mutating ops


async def test_post_without_token_is_forbidden(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post("/bump")
    assert response.status_code == 403
    assert "CSRF token missing" in response.text


async def test_post_without_header_is_forbidden(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(
        "/bump",
        cookies={"pylar_csrf": "abc"},
    )
    assert response.status_code == 403


async def test_post_with_mismatched_token_is_forbidden(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(
        "/bump",
        cookies={"pylar_csrf": "cookie-value"},
        headers={"x-csrf-token": "header-value"},
    )
    assert response.status_code == 403
    assert "mismatch" in response.text


async def test_post_with_matching_token_passes(
    client: httpx.AsyncClient,
) -> None:
    token = "shared-secret-1234567890"
    response = await client.post(
        "/bump",
        cookies={"pylar_csrf": token},
        headers={"x-csrf-token": token},
    )
    assert response.status_code == 200
    assert response.json() == {"bumped": True}


async def test_put_with_matching_token_passes(
    client: httpx.AsyncClient,
) -> None:
    token = "shared-token"
    response = await client.put(
        "/bump/1",
        cookies={"pylar_csrf": token},
        headers={"x-csrf-token": token},
    )
    assert response.status_code == 200


async def test_delete_with_matching_token_passes(
    client: httpx.AsyncClient,
) -> None:
    token = "shared-token"
    response = await client.delete(
        "/bump/1",
        cookies={"pylar_csrf": token},
        headers={"x-csrf-token": token},
    )
    assert response.status_code == 200


# --------------------------------------------------------------- end-to-end


async def test_get_then_post_using_received_cookie(
    client: httpx.AsyncClient,
) -> None:
    """The realistic flow: GET to receive a cookie, POST echoing it back."""
    initial = await client.get("/ping")
    token = initial.cookies["pylar_csrf"]

    response = await client.post(
        "/bump",
        cookies={"pylar_csrf": token},
        headers={"x-csrf-token": token},
    )
    assert response.status_code == 200
