"""Behavioural tests for :class:`pylar.http.Pipeline`."""

from __future__ import annotations

from pylar.http import Middleware, Pipeline, Request, RequestHandler, Response


class TraceMiddleware:
    """Middleware that records its entry/exit around a shared trace list."""

    def __init__(self, name: str, trace: list[str]) -> None:
        self.name = name
        self.trace = trace

    async def handle(self, request: Request, next_handler: RequestHandler) -> Response:
        self.trace.append(f"{self.name}:before")
        response = await next_handler(request)
        self.trace.append(f"{self.name}:after")
        return response


class ShortCircuitMiddleware:
    def __init__(self, body: bytes) -> None:
        self.body = body

    async def handle(self, request: Request, next_handler: RequestHandler) -> Response:
        return Response(content=self.body, status_code=418)


def _empty_request() -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "query_string": b"",
        "scheme": "http",
        "server": ("test", 80),
    }
    return Request(scope)


async def _final_handler(request: Request) -> Response:
    return Response(content=b"ok", status_code=200)


async def test_pipeline_runs_middlewares_in_order() -> None:
    trace: list[str] = []
    pipeline = Pipeline([
        TraceMiddleware("a", trace),
        TraceMiddleware("b", trace),
        TraceMiddleware("c", trace),
    ])

    response = await pipeline.send(_empty_request(), _final_handler)

    assert response.status_code == 200
    assert response.body == b"ok"
    assert trace == [
        "a:before", "b:before", "c:before",
        "c:after", "b:after", "a:after",
    ]


async def test_pipeline_with_no_middlewares_invokes_finalizer_directly() -> None:
    pipeline = Pipeline([])
    response = await pipeline.send(_empty_request(), _final_handler)
    assert response.body == b"ok"


async def test_middleware_can_short_circuit() -> None:
    trace: list[str] = []
    pipeline = Pipeline([
        TraceMiddleware("outer", trace),
        ShortCircuitMiddleware(b"teapot"),
        TraceMiddleware("never", trace),
    ])

    async def finalizer(request: Request) -> Response:
        trace.append("finalizer")
        return Response(content=b"unreachable")

    response = await pipeline.send(_empty_request(), finalizer)

    assert response.status_code == 418
    assert response.body == b"teapot"
    assert trace == ["outer:before", "outer:after"]
    assert "finalizer" not in trace
    assert "never:before" not in trace


def test_middleware_protocol_is_runtime_checkable() -> None:
    trace: list[str] = []
    instance: Middleware = TraceMiddleware("x", trace)
    assert isinstance(instance, Middleware)
