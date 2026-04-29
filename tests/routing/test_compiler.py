"""End-to-end tests for the route compiler — driven through the ASGI app."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from pylar.foundation import (
    AppConfig,
    Application,
    Container,
    ServiceProvider,
)
from pylar.http import HttpKernel, Request, RequestHandler, Response, json
from pylar.routing import Router

# --------------------------------------------------------------------- handlers


async def home(request: Request) -> Response:
    return json({"page": "home"})


async def show_user(request: Request, user_id: int) -> Response:
    return json({"user_id": user_id, "type": type(user_id).__name__})


class GreetingService:
    def greet(self, name: str) -> str:
        return f"hello {name}"


class GreetController:
    """A controller whose constructor depends on a service from the container."""

    def __init__(self, greeter: GreetingService) -> None:
        self.greeter = greeter

    async def show(self, request: Request, name: str) -> Response:
        return json({"message": self.greeter.greet(name)})


# ------------------------------------------------------------------- middleware


class HeaderMiddleware:
    async def handle(self, request: Request, next_handler: RequestHandler) -> Response:
        response = await next_handler(request)
        response.headers["x-mw"] = "outer"
        return response


class InnerHeaderMiddleware:
    async def handle(self, request: Request, next_handler: RequestHandler) -> Response:
        response = await next_handler(request)
        # Set first; HeaderMiddleware will overwrite x-mw on the way out.
        response.headers["x-inner"] = "inner"
        return response


# ----------------------------------------------------------------- bootstrapping


class _RouteServiceProvider(ServiceProvider):
    """Builds the Router and registers it as a singleton."""

    def register(self, container: Container) -> None:
        router = Router()
        router.get("/", home)
        router.get("/users/{user_id:int}", show_user)
        router.get("/greet/{name}", GreetController.show)

        api = router.group(prefix="/api", middleware=[HeaderMiddleware])
        api.get("/ping", home, middleware=[InnerHeaderMiddleware])

        container.singleton(Router, lambda: router)


@pytest.fixture
async def client() -> httpx.AsyncClient:
    app = Application(
        base_path=Path("/tmp/pylar-routing-test"),
        config=AppConfig(name="routing-test", debug=True, providers=(_RouteServiceProvider,)),
    )
    await app.bootstrap()
    kernel = HttpKernel(app)
    transport = httpx.ASGITransport(app=kernel.asgi())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await app.shutdown()


async def test_function_route_returns_json(client: httpx.AsyncClient) -> None:
    response = await client.get("/")
    assert response.status_code == 200
    assert response.json() == {"page": "home"}


async def test_typed_path_param_is_converted_to_int(client: httpx.AsyncClient) -> None:
    response = await client.get("/users/42")
    assert response.status_code == 200
    assert response.json() == {"user_id": 42, "type": "int"}


async def test_controller_dependencies_are_resolved_from_container(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/greet/world")
    assert response.status_code == 200
    assert response.json() == {"message": "hello world"}


async def test_group_middleware_runs_before_inner(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/ping")
    assert response.status_code == 200
    # Both middlewares ran:
    assert response.headers.get("x-inner") == "inner"
    assert response.headers.get("x-mw") == "outer"


async def test_unmatched_path_returns_404(client: httpx.AsyncClient) -> None:
    response = await client.get("/missing")
    assert response.status_code == 404
