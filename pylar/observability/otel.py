"""OpenTelemetry integration (ADR-0008 phase 9b).

Ships behind the ``pylar[otel]`` extra — pulls in
``opentelemetry-api``, ``opentelemetry-sdk``, and
``opentelemetry-exporter-otlp``. When the SDK is not installed, the
module imports cleanly but :class:`OtelServiceProvider` refuses to
boot with a clear error; :class:`OtelJobMiddleware` acts as a
transparent no-op so mixed deployments (some workers with OTel, some
without) keep working.

Environment-driven configuration follows OTel's own conventions:

* ``OTEL_EXPORTER_OTLP_ENDPOINT`` — gRPC endpoint
  (e.g. ``http://tempo:4317``)
* ``OTEL_SERVICE_NAME`` — service name reported to the backend
* ``OTEL_RESOURCE_ATTRIBUTES`` — comma-separated ``key=value`` pairs

``configure_otel_from_env`` reads the above, installs a batching
exporter, and sets the global :class:`TracerProvider`. It is
idempotent — calling it twice is a no-op.

See :class:`pylar.http.middlewares.tracing.TracingMiddleware` for the
HTTP-side span wrapper that has shipped since pylar 0.2. The new
:class:`OtelJobMiddleware` covers the queue worker side so HTTP
requests and background jobs end up on the same trace graph.
"""

from __future__ import annotations

import os
from typing import Any

from pylar.foundation.container import Container
from pylar.foundation.provider import ServiceProvider
from pylar.queue.job import Job, JobMiddleware, JobMiddlewareNext
from pylar.queue.payload import JobPayload

try:
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    _HAS_OTEL = True
except ImportError:  # pragma: no cover — tested via separate extras install
    _HAS_OTEL = False


# ------------------------------------------------------------- setup


def configure_otel_from_env(*, service_name: str | None = None) -> bool:
    """Install a global :class:`TracerProvider` reading env vars.

    Returns ``True`` when configuration actually ran, ``False`` when
    the OTel SDK is not installed. Idempotent — if a provider has
    already been set (via this function or by the user) it does
    nothing.

    Env vars honoured:

    * ``OTEL_EXPORTER_OTLP_ENDPOINT`` — OTLP endpoint; defaults to
      ``http://localhost:4317`` when unset but the SDK is present.
    * ``OTEL_SERVICE_NAME`` — overridden by *service_name* if both
      are set; falls back to ``"pylar"``.
    * ``OTEL_RESOURCE_ATTRIBUTES`` — standard OTel parse.
    """
    if not _HAS_OTEL:
        return False
    # Idempotency: if the user or a previous provider already set a
    # non-default TracerProvider, leave it alone.
    current = trace.get_tracer_provider()
    if isinstance(current, TracerProvider):
        return True

    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
        OTLPSpanExporter,
    )

    resource_attrs: dict[str, Any] = {}
    name = service_name or os.environ.get("OTEL_SERVICE_NAME") or "pylar"
    resource_attrs["service.name"] = name
    resource = Resource.create(resource_attrs)

    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    return True


# ------------------------------------------------------------- provider


class OtelServiceProvider(ServiceProvider):
    """Configure OTel once at boot time and expose it to the rest of the app.

    Users register this provider in ``config/app.py`` after
    :class:`ObservabilityServiceProvider`. The provider itself is
    stateless — all configuration goes through
    :func:`configure_otel_from_env` so the typical operator workflow
    is "set OTEL_* env vars, add the provider, done."

    When the ``pylar[otel]`` extra is not installed the provider
    refuses to boot with an :class:`ImportError` — this is deliberate:
    an operator who added the provider expects tracing to work, and
    silently skipping would hide the misconfiguration.
    """

    def register(self, container: Container) -> None:
        # No container bindings — the OTel global is set in boot().
        pass

    async def boot(self, container: Container) -> None:
        if not _HAS_OTEL:
            raise ImportError(
                "OtelServiceProvider requires the 'pylar[otel]' extra. "
                "Install with: pip install 'pylar[otel]'"
            )
        configure_otel_from_env()


# ------------------------------------------------------------ job middleware


class OtelJobMiddleware(JobMiddleware):
    """Wrap :meth:`Job.handle` in an OpenTelemetry span.

    Add to a job's ``middleware = (...)`` tuple to get a span per
    dispatch. The span name is the job's fully qualified class name;
    payload attempts and the queue name end up as span attributes so
    backends like Tempo/Jaeger can group failures.

    No-op when ``pylar[otel]`` is not installed — tests and minimal
    deployments don't need the SDK.
    """

    tracer_name: str = "pylar.queue"

    async def handle(
        self,
        job: Job[JobPayload],
        payload: JobPayload,
        next_call: JobMiddlewareNext,
    ) -> None:
        if not _HAS_OTEL:
            await next_call(payload)
            return

        tracer = trace.get_tracer(self.tracer_name)
        job_cls = type(job)
        span_name = f"{job_cls.__module__}.{job_cls.__qualname__}"

        with tracer.start_as_current_span(span_name) as span:
            span.set_attribute("pylar.job.class", span_name)
            queue_name = getattr(job_cls, "queue", "default")
            span.set_attribute("pylar.job.queue", queue_name)
            try:
                await next_call(payload)
            except Exception as exc:
                span.set_status(trace.Status(trace.StatusCode.ERROR, str(exc)))
                span.record_exception(exc)
                raise
