"""Tests for observability phase 9b — OpenTelemetry wiring (ADR-0008)."""

from __future__ import annotations

import pytest

from pylar.observability.otel import (
    _HAS_OTEL,
    OtelJobMiddleware,
    OtelServiceProvider,
    configure_otel_from_env,
)
from pylar.queue import Job, JobPayload


class _P(JobPayload):
    x: int


class _NoopJob(Job[_P]):
    payload_type = _P

    def __init__(self) -> None:
        pass

    async def handle(self, payload: _P) -> None:
        pass


async def test_otel_job_middleware_is_noop_without_sdk() -> None:
    """When OTel is unavailable the middleware must not interfere.

    This is the shape of the contract — ``_HAS_OTEL`` may be True in
    CI environments that install the extras, in which case the test
    still passes (the middleware calls ``next_call`` either way).
    """
    middleware = OtelJobMiddleware()
    job = _NoopJob()
    calls: list[_P] = []

    async def next_call(payload: _P) -> None:  # type: ignore[override]
        calls.append(payload)

    payload = _P(x=1)
    await middleware.handle(job, payload, next_call)  # type: ignore[arg-type]
    assert calls == [payload]


async def test_otel_provider_raises_without_extras() -> None:
    """The provider fails loudly if the extras slot is missing.

    The behaviour is opt-in: silently skipping would hide a
    misconfiguration (an operator who registered the provider expects
    tracing). We can only assert this path reliably when the OTel SDK
    is actually absent; otherwise skip the test.
    """
    if _HAS_OTEL:
        pytest.skip("OTel SDK installed — the no-extras path can't be exercised")
    from pathlib import Path

    from pylar.foundation import AppConfig, Application

    app = Application(
        base_path=Path("/tmp/pylar-otel-test"),
        config=AppConfig(name="t", debug=True, providers=()),
    )
    provider = OtelServiceProvider(app)
    with pytest.raises(ImportError, match="pylar\\[otel\\]"):
        await provider.boot(app.container)


@pytest.mark.skipif(not _HAS_OTEL, reason="requires pylar[otel]")
async def test_configure_otel_from_env_installs_tracer_provider() -> None:
    """With the SDK installed, calling configure installs a TracerProvider."""
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider

    ok = configure_otel_from_env(service_name="pylar-test")
    assert ok is True
    assert isinstance(trace.get_tracer_provider(), TracerProvider)
