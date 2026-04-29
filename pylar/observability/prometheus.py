"""Prometheus integration (ADR-0008 phase 9c).

Ships behind the ``pylar[prometheus]`` extra — pulls in
``prometheus-client``. The module imports cleanly without the extra
so tests and minimal deployments don't need the dependency; attempts
to actually *use* any surface (middleware, provider) fall back to a
no-op mode when the client library is absent.

Exposed surface:

* :class:`PrometheusMiddleware` — per-request counter + histogram on
  method / path / status class.
* :class:`PrometheusJobMiddleware` — per-job counter + histogram on
  job class / queue / outcome (``success`` / ``failure``).
* :class:`PrometheusServiceProvider` — mounts ``GET /metrics`` on the
  application router during ``boot``. Configurable via
  :class:`PrometheusConfig`.

All metric names and labels follow the
`OpenTelemetry semantic conventions`_ where applicable so an ops team
reusing dashboards from other languages / frameworks gets consistent
naming.

.. _OpenTelemetry semantic conventions:
   https://github.com/open-telemetry/semantic-conventions
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from pylar.foundation.container import Container
from pylar.foundation.provider import ServiceProvider
from pylar.http.middleware import RequestHandler
from pylar.http.request import Request
from pylar.http.response import Response
from pylar.queue.job import Job, JobMiddleware, JobMiddlewareNext
from pylar.queue.payload import JobPayload

try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        CollectorRegistry,
        Counter,
        Histogram,
        generate_latest,
    )

    _HAS_PROM = True
except ImportError:  # pragma: no cover — tested via separate extras install
    _HAS_PROM = False


# --------------------------------------------------------- metric factories


def _build_http_metrics(
    registry: CollectorRegistry,
) -> tuple[Counter, Histogram]:
    requests_total = Counter(
        "pylar_http_requests_total",
        "HTTP requests handled, labelled by method / status class.",
        labelnames=("method", "status_class"),
        registry=registry,
    )
    request_duration = Histogram(
        "pylar_http_request_duration_seconds",
        "Wall-clock HTTP request duration in seconds, by method.",
        labelnames=("method",),
        registry=registry,
    )
    return requests_total, request_duration


def _build_job_metrics(
    registry: CollectorRegistry,
) -> tuple[Counter, Histogram]:
    jobs_total = Counter(
        "pylar_queue_jobs_total",
        "Queue jobs processed by the worker, by job class / queue / outcome.",
        labelnames=("job", "queue", "outcome"),
        registry=registry,
    )
    job_duration = Histogram(
        "pylar_queue_job_duration_seconds",
        "Queue job handler duration in seconds, by job class / queue.",
        labelnames=("job", "queue"),
        registry=registry,
    )
    return jobs_total, job_duration


# ------------------------------------------------------------ config + state


@dataclass(frozen=True)
class PrometheusConfig:
    """Toggle + path for the metrics endpoint.

    Applications override via
    ``container.instance(PrometheusConfig, PrometheusConfig(...))``;
    the provider respects whichever binding wins.
    """

    enabled: bool = True
    path: str = "/metrics"


class _PrometheusState:
    """Holds registry + collector handles shared by middleware and provider.

    A single state object is bound as a singleton so the HTTP
    middleware, the job middleware, and the ``/metrics`` endpoint all
    read and write the same collectors.
    """

    def __init__(
        self,
        *,
        registry: CollectorRegistry | None = None,
    ) -> None:
        if not _HAS_PROM:
            self.registry = None
            self.http_requests_total = None
            self.http_duration = None
            self.jobs_total = None
            self.job_duration = None
            return

        self.registry = registry or CollectorRegistry(auto_describe=True)
        self.http_requests_total, self.http_duration = _build_http_metrics(
            self.registry
        )
        self.jobs_total, self.job_duration = _build_job_metrics(self.registry)

    def render(self) -> tuple[bytes, str]:
        """Serialise every metric in the registry as the Prometheus text format."""
        if not _HAS_PROM or self.registry is None:
            return b"", "text/plain"
        return generate_latest(self.registry), CONTENT_TYPE_LATEST


# --------------------------------------------------------- HTTP middleware


class PrometheusMiddleware:
    """Count + time every HTTP request and tag with its status class."""

    def __init__(self, state: _PrometheusState) -> None:
        self._state = state

    async def handle(
        self, request: Request, next_handler: RequestHandler
    ) -> Response:
        reqs = self._state.http_requests_total
        hist = self._state.http_duration
        if not _HAS_PROM or reqs is None or hist is None:
            return await next_handler(request)

        start = time.perf_counter()
        try:
            response = await next_handler(request)
        except Exception:
            elapsed = time.perf_counter() - start
            reqs.labels(method=request.method, status_class="5xx").inc()
            hist.labels(method=request.method).observe(elapsed)
            raise

        elapsed = time.perf_counter() - start
        reqs.labels(
            method=request.method,
            status_class=f"{response.status_code // 100}xx",
        ).inc()
        hist.labels(method=request.method).observe(elapsed)
        return response


# --------------------------------------------------------- Job middleware


class PrometheusJobMiddleware(JobMiddleware):
    """Count + time every queue job, tagging success vs failure."""

    def __init__(self, state: _PrometheusState) -> None:
        self._state = state

    async def handle(
        self,
        job: Job[JobPayload],
        payload: JobPayload,
        next_call: JobMiddlewareNext,
    ) -> None:
        jobs = self._state.jobs_total
        hist = self._state.job_duration
        if not _HAS_PROM or jobs is None or hist is None:
            await next_call(payload)
            return

        job_cls = type(job)
        labels = {
            "job": f"{job_cls.__module__}.{job_cls.__qualname__}",
            "queue": getattr(job_cls, "queue", "default"),
        }
        start = time.perf_counter()
        try:
            await next_call(payload)
        except Exception:
            jobs.labels(outcome="failure", **labels).inc()
            raise
        finally:
            hist.labels(**labels).observe(time.perf_counter() - start)
        jobs.labels(outcome="success", **labels).inc()


# ------------------------------------------------------------ provider


class PrometheusServiceProvider(ServiceProvider):
    """Bind the collector state and mount ``/metrics``.

    Without the extras slot, the provider skips the mount and leaves
    the middleware in no-op mode. With the extras slot installed and
    :class:`PrometheusConfig.enabled` true, ``GET /metrics`` returns
    the Prometheus text format from the shared registry.
    """

    def register(self, container: Container) -> None:
        if not container.has(PrometheusConfig):
            container.instance(PrometheusConfig, PrometheusConfig())
        if not container.has(_PrometheusState):
            container.instance(_PrometheusState, _PrometheusState())

    async def boot(self, container: Container) -> None:
        if not _HAS_PROM:
            return

        cfg = container.make(PrometheusConfig)
        if not cfg.enabled:
            return

        from pylar.http.response import Response
        from pylar.routing import Router

        state = container.make(_PrometheusState)
        router = container.make(Router)

        async def metrics_endpoint() -> Response:
            body, content_type = state.render()
            return Response(
                content=body,
                media_type=content_type,
            )

        router.get(cfg.path, metrics_endpoint, name="prometheus.metrics")
