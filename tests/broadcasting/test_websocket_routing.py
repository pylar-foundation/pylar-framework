"""End-to-end test for WebSocket route compilation via Starlette TestClient."""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from pylar.broadcasting import (
    Broadcaster,
    BroadcastingServiceProvider,
    MemoryBroadcaster,
    WebSocket,
    WebSocketDisconnect,
)
from pylar.foundation import (
    AppConfig,
    Application,
    Container,
    ServiceProvider,
)
from pylar.http import HttpKernel
from pylar.routing import Router

# --------------------------------------------------------------------- handlers


async def echo(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_text(f"echo: {data}")
    except WebSocketDisconnect:
        return


async def info(websocket: WebSocket, broadcaster: Broadcaster) -> None:
    await websocket.accept()
    await websocket.send_json({"broadcaster": type(broadcaster).__name__})
    await websocket.close()


# ----------------------------------------------------------------- providers


class _RouteProvider(ServiceProvider):
    def register(self, container: Container) -> None:
        router = Router()
        router.websocket("/ws/echo", echo, name="ws.echo")
        router.websocket("/ws/info", info)
        container.singleton(Router, lambda: router)


@pytest.fixture
def app() -> Application:
    return Application(
        base_path=Path("/tmp/pylar-broadcasting-test"),
        config=AppConfig(
            name="broadcasting-test",
            debug=True,
            providers=(BroadcastingServiceProvider, _RouteProvider),
        ),
    )


@pytest.fixture
def client(app: Application) -> TestClient:
    import asyncio

    asyncio.get_event_loop().run_until_complete(app.bootstrap())
    asgi = HttpKernel(app).asgi()
    return TestClient(asgi)


def test_echo_round_trip(client: TestClient) -> None:
    with client.websocket_connect("/ws/echo") as ws:
        ws.send_text("hello")
        assert ws.receive_text() == "echo: hello"
        ws.send_text("world")
        assert ws.receive_text() == "echo: world"


def test_handler_receives_injected_broadcaster(client: TestClient) -> None:
    with client.websocket_connect("/ws/info") as ws:
        payload = ws.receive_json()
    assert payload == {"broadcaster": "MemoryBroadcaster"}


def test_unknown_websocket_path_rejected(client: TestClient) -> None:
    with pytest.raises((WebSocketDisconnect, KeyError, RuntimeError)):
        with client.websocket_connect("/ws/missing"):
            pass


def test_memory_broadcaster_is_default_binding(app: Application) -> None:
    import asyncio

    asyncio.get_event_loop().run_until_complete(app.bootstrap())
    broadcaster = app.container.make(Broadcaster)  # type: ignore[type-abstract]
    assert isinstance(broadcaster, MemoryBroadcaster)
