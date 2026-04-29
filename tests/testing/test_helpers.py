"""Behavioural tests for the testing helpers."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy.orm import Mapped, mapped_column

from pylar.database import (
    ConnectionManager,
    DatabaseConfig,
    Model,
    transaction,
    use_session,
)
from pylar.foundation import Container, ServiceProvider
from pylar.http import Request, Response, json
from pylar.routing import Router
from pylar.testing import (
    Factory,
    create_test_app,
    http_client,
    transactional_session,
)

# --------------------------------------------------------------------- domain


class Widget(Model):
    __tablename__ = "test_widgets"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]


class WidgetFactory(Factory[Widget]):
    @classmethod
    def model_class(cls) -> type[Widget]:
        return Widget

    def definition(self) -> dict[str, object]:
        return {"name": "default-widget"}


# ----------------------------------------------------------------- factory


@pytest.fixture
async def manager() -> AsyncIterator[ConnectionManager]:
    config = DatabaseConfig(url="sqlite+aiosqlite:///:memory:")
    mgr = ConnectionManager(config)
    await mgr.initialize()
    async with mgr.engine.begin() as conn:
        await conn.run_sync(Model.metadata.create_all)
    yield mgr
    await mgr.dispose()


def test_factory_make_returns_unsaved_instance() -> None:
    widget = WidgetFactory().make()
    assert widget.name == "default-widget"
    assert widget.id is None


def test_factory_make_supports_overrides() -> None:
    widget = WidgetFactory().make({"name": "custom"})
    assert widget.name == "custom"


async def test_factory_create_persists_instance(manager: ConnectionManager) -> None:
    async with use_session(manager):
        async with transaction():
            widget = await WidgetFactory().create({"name": "saved"})
        assert widget.id is not None

        fetched = await Widget.query.where(Widget.name == "saved").first()
        assert fetched is not None


# ------------------------------------------------------------ transactional


async def test_transactional_session_rolls_back(manager: ConnectionManager) -> None:
    async with transactional_session(manager) as session:
        session.add(Widget(name="ephemeral"))
        await session.flush()

    # Outside the rollback boundary the row is gone.
    async with use_session(manager) as fresh:
        result = await fresh.execute(
            Widget.query.where(Widget.name == "ephemeral").to_select()
        )
        assert result.scalar_one_or_none() is None


# --------------------------------------------------------------- create_test_app


def test_create_test_app_defaults() -> None:
    app = create_test_app()
    assert app.config.name == "pylar-test"
    assert app.config.debug is True
    assert app.config.providers == ()


def test_create_test_app_accepts_providers() -> None:
    class _Marker(ServiceProvider):
        pass

    app = create_test_app(providers=[_Marker])
    assert app.config.providers == (_Marker,)


# --------------------------------------------------------------------- client


async def hello(request: Request) -> Response:
    return json({"hello": "world"})


class _RouteProvider(ServiceProvider):
    def register(self, container: Container) -> None:
        router = Router()
        router.get("/hello", hello)
        container.singleton(Router, lambda: router)


async def test_http_client_round_trip() -> None:
    app = create_test_app(providers=[_RouteProvider])
    async with http_client(app) as client:
        response = await client.get("/hello")
        assert response.status_code == 200
        assert response.json() == {"hello": "world"}
