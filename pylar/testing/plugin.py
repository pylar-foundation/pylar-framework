"""pytest plugin that ships ready-made fixtures for pylar projects.

The plugin is registered through the ``pytest11`` entry point in
``pyproject.toml``, so installing pylar as a regular dependency is
enough — pytest discovers the fixtures below automatically. The
plugin deliberately does **not** auto-bootstrap a database or HTTP
client by default — every project ships its own provider list, and
guessing it would lead to surprising failures. Build the fixtures you
need on top of the factories below.

Fixtures
--------

* ``pylar_app_factory`` — :func:`pylar.testing.create_test_app`,
  exposed under a fixture name so the test signature documents the
  intent.
* ``pylar_test_app`` — a bare :class:`Application` configured with no
  providers, for tests that only need the core bindings.
* ``assert_response`` — the :class:`TestResponse` constructor, ready
  to wrap an :class:`httpx.Response` for fluent assertions.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable

import httpx
import pytest

from pylar.database.connection import ConnectionManager
from pylar.database.session import override_session
from pylar.foundation import Application
from pylar.testing.application import create_test_app
from pylar.testing.assertions import TestResponse
from pylar.testing.database import in_memory_manager


@pytest.fixture
def pylar_app_factory() -> Callable[..., Application]:
    """Return :func:`create_test_app` for tests that need to spin up an Application.

    Usage::

        async def test_something(pylar_app_factory):
            app = pylar_app_factory(providers=[MyProvider])
            await app.bootstrap()
            ...
            await app.shutdown()
    """
    return create_test_app


@pytest.fixture
def pylar_test_app() -> Application:
    """A bare :class:`Application` configured with no providers.

    Useful for tests that only need the core bindings (Container,
    AppConfig, Application itself). Tests that need their own
    providers should use :func:`pylar_app_factory` instead.
    """
    return create_test_app()


@pytest.fixture
def assert_response() -> Callable[[httpx.Response], TestResponse]:
    """Wrap an :class:`httpx.Response` in :class:`TestResponse` for fluent checks.

    Usage::

        async def test_index(client, assert_response):
            response = await client.get("/api/posts")
            assert_response(response).assert_ok().assert_json_count(3)
    """
    return TestResponse


@pytest.fixture
async def pylar_db_manager() -> AsyncIterator[ConnectionManager]:
    """A fresh in-memory aiosqlite :class:`ConnectionManager` per test.

    Wraps :func:`pylar.testing.in_memory_manager` so the per-test
    boilerplate of "spin up an engine, create the schema from
    Model.metadata, dispose it on teardown" collapses to one line in
    the test signature::

        async def test_thing(pylar_db_manager):
            async with use_session(pylar_db_manager) as sess:
                ...

    The fixture creates the schema via
    :func:`pylar.testing.bootstrap_schema`, so any model that has been
    imported by the time the fixture runs will be present.
    """
    async with in_memory_manager() as manager:
        yield manager


@pytest.fixture
async def pylar_db_session(
    pylar_db_manager: ConnectionManager,
) -> AsyncIterator[None]:
    """An ambient transactional session that rolls back at teardown.

    Pair with :func:`pylar_db_manager` to bracket a test in a
    rollback-on-exit transaction. The fixture binds the session to
    :func:`pylar.database.current_session` so model code under test
    sees an ambient session without any extra wiring.
    """
    session = pylar_db_manager.session_factory()
    async with override_session(session):
        try:
            yield
        finally:
            await session.rollback()
            await session.close()


def pytest_configure(config: pytest.Config) -> None:
    """Register pylar's pytest markers so they don't trigger warnings."""
    config.addinivalue_line(
        "markers",
        "pylar: marks a test that exercises a pylar Application end-to-end",
    )


__all__ = [
    "assert_response",
    "pylar_app_factory",
    "pylar_db_manager",
    "pylar_db_session",
    "pylar_test_app",
    "pytest_configure",
]
