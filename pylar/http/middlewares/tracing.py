"""OpenTelemetry tracing middleware.

Creates a span for every HTTP request with method, path, status code,
and request ID. Integrates with any OpenTelemetry-compatible backend
(Jaeger, Zipkin, Datadog, New Relic) via the standard OTel SDK.

Install via ``pylar[tracing]`` (pulls in ``opentelemetry-api`` +
``opentelemetry-sdk``). When the OTel SDK is not installed the
middleware is a transparent no-op — applications that don't need
tracing pay no import cost.

Usage::

    from pylar.http.middlewares.tracing import TracingMiddleware

    web = router.group(middleware=[TracingMiddleware])

Configure the OTel exporter in your service provider's ``boot()``::

    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

    provider = TracerProvider()
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
"""

from __future__ import annotations

from typing import Any

from pylar.http.middleware import RequestHandler
from pylar.http.request import Request
from pylar.http.response import Response

try:
    from opentelemetry import trace
    from opentelemetry.trace import Status, StatusCode

    _trace_api: Any = trace
    _HAS_OTEL = True
except ImportError:
    _trace_api = None
    _HAS_OTEL = False


class TracingMiddleware:
    """Create an OpenTelemetry span for every HTTP request.

    No-op when ``opentelemetry-api`` is not installed.
    """

    tracer_name: str = "pylar.http"

    async def handle(
        self, request: Request, next_handler: RequestHandler
    ) -> Response:
        if not _HAS_OTEL:
            return await next_handler(request)

        tracer = _trace_api.get_tracer(self.tracer_name)
        span_name = f"{request.method} {request.url.path}"

        with tracer.start_as_current_span(span_name) as span:
            span.set_attribute("http.method", request.method)
            span.set_attribute("http.url", str(request.url))
            span.set_attribute("http.target", request.url.path)
            if request.client:
                span.set_attribute("net.peer.ip", request.client.host)

            request_id = request.scope.get("request_id", "")
            if request_id:
                span.set_attribute("pylar.request_id", request_id)

            response = await next_handler(request)

            span.set_attribute("http.status_code", response.status_code)
            if response.status_code >= 400:
                span.set_status(
                    Status(StatusCode.ERROR)
                    if response.status_code >= 500
                    else Status(StatusCode.UNSET)
                )

            return response
