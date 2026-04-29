"""Observability — diagnostic commands + structured logging (ADR-0008).

Phase 9a scope: zero-dependency foundations that every production
install wants on day one:

* :class:`pylar.observability.AboutCommand` — ``pylar about`` dumps
  the resolved application config so operators can see what is
  actually wired up.
* :class:`pylar.observability.DoctorCommand` — ``pylar doctor``
  probes every bound resource (DB, cache, queue, storage, mail) and
  exits non-zero if any fail. CI-friendly readiness gate.
* :func:`pylar.observability.install_json_logging` — one-line
  installer for the structured JSON log formatter with request-id
  correlation.

OpenTelemetry, Prometheus, and Sentry integrations ship in follow-up
phases behind the ``pylar[otel]``, ``pylar[prometheus]``, and
``pylar[sentry]`` extras respectively.
"""

from pylar.observability.commands import AboutCommand
from pylar.observability.doctor import CheckResult, DoctorCommand
from pylar.observability.logging import JsonFormatter, install_json_logging
from pylar.observability.otel import (
    OtelJobMiddleware,
    OtelServiceProvider,
    configure_otel_from_env,
)
from pylar.observability.prometheus import (
    PrometheusConfig,
    PrometheusJobMiddleware,
    PrometheusMiddleware,
    PrometheusServiceProvider,
)
from pylar.observability.provider import ObservabilityServiceProvider
from pylar.observability.sentry import (
    SentryHttpMiddleware,
    SentryJobMiddleware,
    SentryServiceProvider,
    configure_sentry_from_env,
)

__all__ = [
    "AboutCommand",
    "CheckResult",
    "DoctorCommand",
    "JsonFormatter",
    "ObservabilityServiceProvider",
    "OtelJobMiddleware",
    "OtelServiceProvider",
    "PrometheusConfig",
    "PrometheusJobMiddleware",
    "PrometheusMiddleware",
    "PrometheusServiceProvider",
    "SentryHttpMiddleware",
    "SentryJobMiddleware",
    "SentryServiceProvider",
    "configure_otel_from_env",
    "configure_sentry_from_env",
    "install_json_logging",
]
