"""Integration test for :class:`DatabaseSessionMiddleware` driving real queries."""

from __future__ import annotations

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
)
from pylar.foundation import (
    AppConfig,
    Application,
    Container,
    ServiceProvider,
)
from pylar.http import HttpKernel, Request, Response, json
from pylar.routing import Router


class Note(Model):
    __tablename__ = "test_notes"
    id: Mapped[int] = mapped_column(primary_key=True)
    body: Mapped[str]


async def list_notes(request: Request) -> Response:
    notes = await Note.query.order_by(Note.id.asc()).all()
    return json([{"id": n.id, "body": n.body} for n in notes])


class _DatabaseConfigProvider(ServiceProvider):
    def register(self, container: Container) -> None:
        container.instance(
            DatabaseConfig,
            DatabaseConfig(url="sqlite+aiosqlite:///:memory:", echo=False),
        )


class _SchemaProvider(ServiceProvider):
    """Create the schema and seed two rows once the engine is ready."""

    async def boot(self, container: Container) -> None:
        manager = container.make(ConnectionManager)
        async with manager.engine.begin() as conn:
            await conn.run_sync(Model.metadata.create_all)

        # Seed two rows in their own session.
        from pylar.database import use_session

        async with use_session(manager):
            async with transaction():
                from pylar.database import current_session

                sess = current_session()
                sess.add_all([Note(body="first"), Note(body="second")])


class _RouteProvider(ServiceProvider):
    def register(self, container: Container) -> None:
        router = Router()
        router.get("/notes", list_notes, middleware=[DatabaseSessionMiddleware])
        container.singleton(Router, lambda: router)


@pytest.fixture
async def client() -> httpx.AsyncClient:
    app = Application(
        base_path=Path("/tmp/pylar-db-mw-test"),
        config=AppConfig(
            name="db-mw-test",
            debug=True,
            providers=(
                _DatabaseConfigProvider,
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


async def test_request_can_query_through_ambient_session(client: httpx.AsyncClient) -> None:
    response = await client.get("/notes")
    assert response.status_code == 200
    payload = response.json()
    assert [n["body"] for n in payload] == ["first", "second"]
