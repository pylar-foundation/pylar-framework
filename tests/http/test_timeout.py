"""Tests for :class:`TimeoutMiddleware`."""

from __future__ import annotations

import asyncio

import pytest

from pylar.http.middlewares.timeout import TimeoutMiddleware
from pylar.http.request import Request
from pylar.http.response import Response


def _make_request() -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/",
        "query_string": b"",
        "headers": [],
    })


async def test_fast_handler_passes_through() -> None:
    mw = TimeoutMiddleware(seconds=1.0)

    async def handler(_: Request) -> Response:
        return Response(content="ok", status_code=200)

    resp = await mw.handle(_make_request(), handler)
    assert resp.status_code == 200
    assert resp.body == b"ok"


async def test_slow_handler_returns_504() -> None:
    mw = TimeoutMiddleware(seconds=0.05)

    async def slow_handler(_: Request) -> Response:
        await asyncio.sleep(1.0)
        return Response(content="never", status_code=200)

    resp = await mw.handle(_make_request(), slow_handler)
    assert resp.status_code == 504
    assert b"deadline" in resp.body


async def test_handler_exceptions_propagate() -> None:
    """Non-timeout exceptions must bubble up so the compiler can render them."""
    mw = TimeoutMiddleware(seconds=1.0)

    async def failing(_: Request) -> Response:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await mw.handle(_make_request(), failing)


async def test_zero_or_negative_seconds_rejected() -> None:
    with pytest.raises(ValueError, match="must be > 0"):
        TimeoutMiddleware(seconds=0)
    with pytest.raises(ValueError, match="must be > 0"):
        TimeoutMiddleware(seconds=-1.0)


async def test_sub_second_deadline_supported() -> None:
    """Float seconds allow millisecond-precision deadlines."""
    mw = TimeoutMiddleware(seconds=0.01)

    async def slow(_: Request) -> Response:
        await asyncio.sleep(0.5)
        return Response(content="late", status_code=200)

    resp = await mw.handle(_make_request(), slow)
    assert resp.status_code == 504
