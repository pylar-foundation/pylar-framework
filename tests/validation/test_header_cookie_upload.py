"""End-to-end tests for HeaderDTO, CookieDTO, and UploadFile."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from pydantic import Field

from pylar.foundation import AppConfig, Application, Container, ServiceProvider
from pylar.http import HttpKernel, Request, Response, json
from pylar.routing import Router
from pylar.validation import CookieDTO, HeaderDTO, UploadFile


class WebhookHeaders(HeaderDTO):
    signature: str = Field(alias="x-signature")
    delivery_id: str = Field(alias="x-delivery-id")


class SessionCookies(CookieDTO):
    sid: str
    flavour: str = "vanilla"


async def _read_headers(request: Request, headers: WebhookHeaders) -> Response:
    return json({"sig": headers.signature, "delivery": headers.delivery_id})


async def _read_cookies(request: Request, cookies: SessionCookies) -> Response:
    return json({"sid": cookies.sid, "flavour": cookies.flavour})


async def _upload(request: Request, file: UploadFile) -> Response:
    body = await file.read()
    return json({"name": file.filename, "size": len(body)})


class _Routes(ServiceProvider):
    def register(self, container: Container) -> None:
        router = Router()
        router.post("/webhook", _read_headers)
        router.get("/whoami", _read_cookies)
        router.post("/upload", _upload)
        container.singleton(Router, lambda: router)


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = Application(
        base_path=Path("/tmp/pylar-validation-test"),
        config=AppConfig(
            name="validation-test",
            debug=True,
            providers=(_Routes,),
        ),
    )
    await app.bootstrap()
    transport = httpx.ASGITransport(app=HttpKernel(app).asgi())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await app.shutdown()


# ----------------------------------------------------------- HeaderDTO


async def test_header_dto_resolves_aliased_headers(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(
        "/webhook",
        headers={"X-Signature": "abc", "X-Delivery-Id": "42"},
    )
    assert response.status_code == 200
    assert response.json() == {"sig": "abc", "delivery": "42"}


async def test_header_dto_missing_header_returns_422(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post("/webhook", headers={"X-Signature": "abc"})
    assert response.status_code == 422
    assert "errors" in response.json()


# ----------------------------------------------------------- CookieDTO


async def test_cookie_dto_resolves_required_cookies(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/whoami", cookies={"sid": "deadbeef"})
    assert response.status_code == 200
    assert response.json() == {"sid": "deadbeef", "flavour": "vanilla"}


async def test_cookie_dto_default_when_missing(client: httpx.AsyncClient) -> None:
    response = await client.get(
        "/whoami", cookies={"sid": "x", "flavour": "chocolate"}
    )
    assert response.json()["flavour"] == "chocolate"


async def test_cookie_dto_missing_required_returns_422(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/whoami")
    assert response.status_code == 422


# ------------------------------------------------------------ UploadFile


async def test_upload_file_round_trip(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/upload",
        files={"file": ("hello.txt", b"hello world", "text/plain")},
    )
    assert response.status_code == 200
    assert response.json() == {"name": "hello.txt", "size": 11}


async def test_upload_file_missing_field_returns_422(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(
        "/upload",
        files={"other": ("a.txt", b"x", "text/plain")},
    )
    assert response.status_code == 422
