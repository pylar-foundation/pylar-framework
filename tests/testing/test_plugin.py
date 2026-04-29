"""Tests for the pytest plugin shipped with pylar.testing."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx

from pylar.foundation import Application, ServiceProvider
from pylar.testing import TestResponse


class _MarkerProvider(ServiceProvider):
    """Lets us assert that the factory threads providers through."""


def test_pylar_app_factory_returns_callable(
    pylar_app_factory: Callable[..., Application],
) -> None:
    app = pylar_app_factory(providers=[_MarkerProvider])
    assert isinstance(app, Application)
    assert app.config.providers == (_MarkerProvider,)
    assert app.config.name == "pylar-test"


def test_pylar_test_app_no_providers(pylar_test_app: Application) -> None:
    assert isinstance(pylar_test_app, Application)
    assert pylar_test_app.config.providers == ()


def test_assert_response_fixture_wraps_httpx_response(
    assert_response: Callable[[httpx.Response], TestResponse],
) -> None:
    request = httpx.Request("GET", "http://test/")
    response = httpx.Response(
        status_code=201,
        headers={"content-type": "application/json"},
        content=json.dumps({"id": 7}).encode(),
        request=request,
    )

    wrapped = assert_response(response)
    assert isinstance(wrapped, TestResponse)
    wrapped.assert_created().assert_json_contains({"id": 7})
