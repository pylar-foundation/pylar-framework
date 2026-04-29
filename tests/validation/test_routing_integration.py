"""End-to-end test: RequestDTO auto-resolved by the router via httpx ASGI."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from pydantic import Field

from pylar.foundation import (
    AppConfig,
    Application,
    Container,
    ServiceProvider,
)
from pylar.http import HttpKernel, Request, Response, json
from pylar.routing import Router
from pylar.validation import RequestDTO


class CreateUserDTO(RequestDTO):
    email: str
    name: str = Field(min_length=1, max_length=100)
    age: int = 0


class UserController:
    """Module-level controller so that the controller-action detector picks it up."""

    async def store(self, request: Request, dto: CreateUserDTO) -> Response:
        return json(
            {"created": {"email": dto.email, "name": dto.name, "age": dto.age}},
            status=201,
        )


async def search(request: Request, query: SearchDTO) -> Response:
    return json({"q": query.q, "limit": query.limit})


class SearchDTO(RequestDTO):
    q: str
    limit: int = 10


class _RouteProvider(ServiceProvider):
    def register(self, container: Container) -> None:
        router = Router()
        router.post("/users", UserController.store)
        router.get("/search", search)
        container.singleton(Router, lambda: router)


@pytest.fixture
async def client() -> httpx.AsyncClient:
    app = Application(
        base_path=Path("/tmp/pylar-validation-test"),
        config=AppConfig(name="validation-test", debug=True, providers=(_RouteProvider,)),
    )
    await app.bootstrap()
    transport = httpx.ASGITransport(app=HttpKernel(app).asgi())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await app.shutdown()


async def test_post_with_valid_json_returns_201(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/users",
        json={"email": "alice@example.com", "name": "Alice", "age": 30},
    )
    assert response.status_code == 201
    assert response.json() == {
        "created": {"email": "alice@example.com", "name": "Alice", "age": 30}
    }


async def test_post_with_invalid_payload_returns_422_with_errors(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post("/users", json={"email": "x", "name": ""})
    assert response.status_code == 422
    payload = response.json()
    assert "errors" in payload
    locations = {tuple(err["loc"]) for err in payload["errors"]}
    assert ("name",) in locations


async def test_post_with_extra_field_returns_422(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/users",
        json={"email": "x@y", "name": "Bob", "unknown": "field"},
    )
    assert response.status_code == 422
    payload = response.json()
    locations = {tuple(err["loc"]) for err in payload["errors"]}
    assert ("unknown",) in locations


async def test_post_with_invalid_json_returns_422(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/users",
        content=b"not json",
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 422
    assert response.json()["errors"][0]["type"] == "body.malformed"


async def test_get_with_query_params_resolves_dto(client: httpx.AsyncClient) -> None:
    response = await client.get("/search", params={"q": "python", "limit": "25"})
    assert response.status_code == 200
    assert response.json() == {"q": "python", "limit": 25}


async def test_get_with_missing_required_query_param_returns_422(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/search")
    assert response.status_code == 422
    locations = {tuple(err["loc"]) for err in response.json()["errors"]}
    assert ("q",) in locations
