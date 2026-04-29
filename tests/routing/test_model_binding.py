"""End-to-end tests for route model binding.

When a handler parameter is annotated with a :class:`pylar.database.Model`
subclass, pylar's routing layer fetches the matching row by primary key
before calling the handler. Missing rows raise
:class:`pylar.http.NotFound` so the route compiler renders a 404 with no
per-controller boilerplate.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from sqlalchemy.orm import Mapped, mapped_column

from pylar.database import (
    ConnectionManager,
    DatabaseConfig,
    DatabaseServiceProvider,
    DatabaseSessionMiddleware,
    Model,
    transaction,
    use_session,
)
from pylar.foundation import (
    AppConfig,
    Application,
    Container,
    ServiceProvider,
)
from pylar.http import HttpKernel, Request, Response, json
from pylar.routing import Router

# --------------------------------------------------------------------- model


class Widget(Model):
    __tablename__ = "test_route_binding_widgets"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]


# ---------------------------------------------------------------- handlers


async def show_widget(request: Request, widget: Widget) -> Response:
    """Handler with model binding via parameter annotation."""
    return json({"id": widget.id, "name": widget.name})


class WidgetController:
    async def show(self, request: Request, widget: Widget) -> Response:
        return json({"id": widget.id, "name": widget.name, "via": "controller"})


# ----------------------------------------------------------------- providers


class _ConfigProvider(ServiceProvider):
    def register(self, container: Container) -> None:
        container.instance(
            DatabaseConfig,
            DatabaseConfig(url="sqlite+aiosqlite:///:memory:"),
        )


class _SchemaProvider(ServiceProvider):
    async def boot(self, container: Container) -> None:
        manager = container.make(ConnectionManager)
        async with manager.engine.begin() as conn:
            await conn.run_sync(Model.metadata.create_all)
        async with use_session(manager):
            async with transaction():
                await Widget.query.save(Widget(name="alpha"))
                await Widget.query.save(Widget(name="beta"))


class _RouteProvider(ServiceProvider):
    def register(self, container: Container) -> None:
        router = Router()
        api = router.group(middleware=[DatabaseSessionMiddleware])
        api.get("/widgets/{widget}", show_widget)
        api.get("/controlled/{widget}", WidgetController.show)
        container.singleton(Router, lambda: router)


# ----------------------------------------------------------------- fixtures


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = Application(
        base_path=Path("/tmp/pylar-routing-binding"),
        config=AppConfig(
            name="binding-test",
            debug=True,
            providers=(
                _ConfigProvider,
                DatabaseServiceProvider,
                _SchemaProvider,
                _RouteProvider,
            ),
        ),
    )
    await app.bootstrap()
    transport = httpx.ASGITransport(app=HttpKernel(app).asgi())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await app.shutdown()


# ------------------------------------------------------------------------ tests


async def test_function_handler_receives_resolved_instance(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/widgets/1")
    assert response.status_code == 200
    assert response.json() == {"id": 1, "name": "alpha"}


async def test_controller_handler_receives_resolved_instance(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/controlled/2")
    assert response.status_code == 200
    assert response.json() == {"id": 2, "name": "beta", "via": "controller"}


async def test_missing_row_returns_404(client: httpx.AsyncClient) -> None:
    response = await client.get("/widgets/9999")
    assert response.status_code == 404
