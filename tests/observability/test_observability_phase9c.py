"""Tests for observability phase 9c — Prometheus wiring (ADR-0008)."""

from __future__ import annotations

import pytest

from pylar.observability.prometheus import (
    _HAS_PROM,
    PrometheusConfig,
    PrometheusJobMiddleware,
    PrometheusMiddleware,
    _PrometheusState,
)
from pylar.queue import Job, JobPayload


class _P(JobPayload):
    v: int


class _OkJob(Job[_P]):
    payload_type = _P

    def __init__(self) -> None:
        pass

    async def handle(self, payload: _P) -> None:
        pass


class _BoomJob(Job[_P]):
    payload_type = _P

    def __init__(self) -> None:
        pass

    async def handle(self, payload: _P) -> None:
        raise RuntimeError("boom")


async def test_prometheus_middleware_is_noop_without_extras() -> None:
    """The HTTP middleware must pass through when the extras slot is missing.

    When the extra *is* installed the state is populated and the
    middleware records — but next_handler still runs exactly once.
    """
    from pylar.http.request import Request
    from pylar.http.response import Response

    state = _PrometheusState()
    mw = PrometheusMiddleware(state)

    called: list[Request] = []

    async def next_handler(req: Request) -> Response:
        called.append(req)
        return Response(content=b"ok", status_code=200)

    # Fake request object — middleware only reads .method + status_code.
    class _FakeRequest:
        method = "GET"

    resp = await mw.handle(_FakeRequest(), next_handler)  # type: ignore[arg-type]
    assert resp.status_code == 200
    assert len(called) == 1


async def test_prometheus_job_middleware_records_success_and_failure_paths() -> None:
    """Success runs next_call; failure still runs it and re-raises."""
    mw = PrometheusJobMiddleware(_PrometheusState())

    ran: list[_P] = []

    async def next_ok(p: _P) -> None:
        ran.append(p)

    async def next_boom(p: _P) -> None:
        ran.append(p)
        raise RuntimeError("boom")

    payload = _P(v=1)
    await mw.handle(_OkJob(), payload, next_ok)  # type: ignore[arg-type]
    assert ran == [payload]

    ran.clear()
    with pytest.raises(RuntimeError, match="boom"):
        await mw.handle(_BoomJob(), payload, next_boom)  # type: ignore[arg-type]
    assert ran == [payload]


@pytest.mark.skipif(not _HAS_PROM, reason="requires pylar[prometheus]")
async def test_prometheus_state_renders_collectors_under_extras() -> None:
    """With the client installed the state produces valid text output."""
    state = _PrometheusState()
    # Touch the collectors so at least one sample is present.
    state.http_requests_total.labels(method="GET", status_class="2xx").inc()
    body, content_type = state.render()
    assert b"pylar_http_requests_total" in body
    assert content_type.startswith("text/plain")


@pytest.mark.skipif(not _HAS_PROM, reason="requires pylar[prometheus]")
async def test_prometheus_provider_mounts_metrics_endpoint() -> None:
    """With the extras installed GET /metrics exposes the registry text."""

    from pylar.foundation import Container, ServiceProvider
    from pylar.observability import PrometheusServiceProvider
    from pylar.routing import Router
    from pylar.testing import create_test_app, http_client

    class _RouterProvider(ServiceProvider):
        def register(self, container: Container) -> None:
            container.singleton(Router, Router)

    app = create_test_app(providers=[_RouterProvider, PrometheusServiceProvider])
    async with http_client(app) as c:
        r = await c.get("/metrics")
        assert r.status_code == 200
        assert "pylar_http_requests_total" in r.text


async def test_prometheus_config_is_singleton_after_register() -> None:
    """The provider installs a default config if the user didn't bind one."""
    from pylar.foundation import Container

    container = Container()
    from pathlib import Path

    from pylar.foundation import AppConfig, Application
    from pylar.observability import PrometheusServiceProvider

    app = Application(
        base_path=Path("/tmp/prom-test"),
        config=AppConfig(name="t", debug=True, providers=()),
    )
    provider = PrometheusServiceProvider(app)
    provider.register(container)
    assert container.make(PrometheusConfig).path == "/metrics"
