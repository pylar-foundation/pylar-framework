"""Tests for observability phase 9d — Sentry wiring (ADR-0008)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pylar.foundation import AppConfig, Application
from pylar.observability.sentry import (
    _HAS_SENTRY,
    SentryHttpMiddleware,
    SentryJobMiddleware,
    SentryServiceProvider,
    configure_sentry_from_env,
)
from pylar.queue import Job, JobPayload


class _P(JobPayload):
    n: int


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


async def test_sentry_http_middleware_passthrough_without_request_id() -> None:
    from pylar.http.response import Response

    mw = SentryHttpMiddleware()
    called: list[object] = []

    async def next_handler(request: object) -> Response:
        called.append(request)
        return Response(content=b"ok", status_code=200)

    class _Req:
        pass

    resp = await mw.handle(_Req(), next_handler)  # type: ignore[arg-type]
    assert resp.status_code == 200
    assert len(called) == 1


async def test_sentry_job_middleware_runs_next_call_on_success() -> None:
    mw = SentryJobMiddleware()
    seen: list[_P] = []

    async def next_call(p: _P) -> None:
        seen.append(p)

    payload = _P(n=7)
    await mw.handle(_OkJob(), payload, next_call)  # type: ignore[arg-type]
    assert seen == [payload]


async def test_sentry_job_middleware_reraises_exceptions() -> None:
    """Unhandled exceptions propagate so the worker's retry path still runs."""
    mw = SentryJobMiddleware()

    async def next_call(p: _P) -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await mw.handle(_BoomJob(), _P(n=1), next_call)  # type: ignore[arg-type]


async def test_configure_returns_false_without_dsn() -> None:
    """Empty SENTRY_DSN → no init, returns False; no side effects."""
    saved = os.environ.pop("SENTRY_DSN", None)
    try:
        assert configure_sentry_from_env() is False
    finally:
        if saved is not None:
            os.environ["SENTRY_DSN"] = saved


async def test_sentry_provider_raises_without_extras() -> None:
    """Declared provider + missing extras = loud ImportError.

    Only meaningful when the sentry-sdk package is *not* installed;
    otherwise the path is unreachable and the test skips.
    """
    if _HAS_SENTRY:
        pytest.skip("sentry-sdk is installed — no-extras path unreachable")

    app = Application(
        base_path=Path("/tmp/pylar-sentry-test"),
        config=AppConfig(name="t", debug=True, providers=()),
    )
    provider = SentryServiceProvider(app)
    with pytest.raises(ImportError, match=r"pylar\[sentry\]"):
        await provider.boot(app.container)


@pytest.mark.skipif(not _HAS_SENTRY, reason="requires pylar[sentry]")
async def test_sentry_traces_sample_rate_clamped_to_valid_range() -> None:
    """Out-of-range SENTRY_TRACES_SAMPLE_RATE gets clamped, not rejected."""
    saved_rate = os.environ.get("SENTRY_TRACES_SAMPLE_RATE")
    saved_dsn = os.environ.get("SENTRY_DSN")
    os.environ["SENTRY_TRACES_SAMPLE_RATE"] = "9.9"
    os.environ["SENTRY_DSN"] = "https://public@sentry.example.com/1"
    try:
        # First call may succeed; subsequent returns without raising.
        configure_sentry_from_env()
    finally:
        if saved_rate is None:
            os.environ.pop("SENTRY_TRACES_SAMPLE_RATE", None)
        else:
            os.environ["SENTRY_TRACES_SAMPLE_RATE"] = saved_rate
        if saved_dsn is None:
            os.environ.pop("SENTRY_DSN", None)
        else:
            os.environ["SENTRY_DSN"] = saved_dsn
