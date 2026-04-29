"""Sentry integration (ADR-0008 phase 9d).

Ships behind the ``pylar[sentry]`` extra. The module imports cleanly
without the SDK; every surface is a no-op so tests and minimal
installs pay nothing.

Surface:

* :func:`configure_sentry_from_env` — idempotent ``sentry_sdk.init``
  driven by standard env vars (``SENTRY_DSN``,
  ``SENTRY_ENVIRONMENT``, ``SENTRY_RELEASE``,
  ``SENTRY_TRACES_SAMPLE_RATE``).
* :class:`SentryServiceProvider` — calls the above in ``boot`` and
  fails loudly when the extras slot is missing.
* :class:`SentryHttpMiddleware` — tags the Sentry scope with the
  active request id (ties the report back to log lines and traces).
* :class:`SentryJobMiddleware` — captures any exception raised inside
  :meth:`Job.handle` with the job's class, queue, payload class, and
  attempt count as structured context, then re-raises so the
  worker's normal retry policy still runs.

HTTP span / request capture is handled by ``sentry_sdk``'s own
Starlette integration when the user enables it in Sentry init. Pylar's
middleware is intentionally small — it only adds the ``request_id``
tag so reports correlate with structured logs and OTel traces.
"""

from __future__ import annotations

import os

from pylar.foundation.container import Container
from pylar.foundation.provider import ServiceProvider
from pylar.http.middleware import RequestHandler
from pylar.http.middlewares.request_id import current_request_id
from pylar.http.request import Request
from pylar.http.response import Response
from pylar.queue.job import Job, JobMiddleware, JobMiddlewareNext
from pylar.queue.payload import JobPayload

try:
    import sentry_sdk

    _HAS_SENTRY = True
except ImportError:  # pragma: no cover — tested via separate extras install
    _HAS_SENTRY = False


# ------------------------------------------------------------- setup


def configure_sentry_from_env() -> bool:
    """Initialise the Sentry SDK from environment variables.

    Reads:

    * ``SENTRY_DSN`` — required; empty/unset skips the init.
    * ``SENTRY_ENVIRONMENT`` — optional; defaults to unset.
    * ``SENTRY_RELEASE`` — optional.
    * ``SENTRY_TRACES_SAMPLE_RATE`` — float in ``[0.0, 1.0]``;
      defaults to ``0.0`` (no performance data).

    Returns ``True`` when ``sentry_sdk.init`` actually ran,
    ``False`` when the SDK is missing or ``SENTRY_DSN`` is empty.
    Idempotent — calling twice after a successful init is a no-op
    because the SDK itself guards against double initialisation.
    """
    if not _HAS_SENTRY:
        return False

    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        return False

    try:
        sample_rate = float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0"))
    except ValueError:
        sample_rate = 0.0

    sentry_sdk.init(
        dsn=dsn,
        environment=os.environ.get("SENTRY_ENVIRONMENT") or None,
        release=os.environ.get("SENTRY_RELEASE") or None,
        traces_sample_rate=max(0.0, min(1.0, sample_rate)),
    )
    return True


# ------------------------------------------------------------- provider


class SentryServiceProvider(ServiceProvider):
    """Initialise the Sentry SDK during the app's boot lifecycle.

    Add after :class:`ObservabilityServiceProvider` in
    ``config/app.py``. The provider itself stores nothing in the
    container — it just hooks the SDK on at the right moment.
    """

    def register(self, container: Container) -> None:
        pass

    async def boot(self, container: Container) -> None:
        if not _HAS_SENTRY:
            raise ImportError(
                "SentryServiceProvider requires the 'pylar[sentry]' extra. "
                "Install with: pip install 'pylar[sentry]'"
            )
        configure_sentry_from_env()


# ------------------------------------------------------------ HTTP middleware


class SentryHttpMiddleware:
    """Tag the active Sentry scope with the per-request correlation id.

    Place after :class:`RequestIdMiddleware` in the stack so the id is
    already populated. Reports produced during the request carry the
    ``request_id`` tag, aligning with the JSON log formatter and OTel
    spans.
    """

    async def handle(
        self, request: Request, next_handler: RequestHandler
    ) -> Response:
        if not _HAS_SENTRY:
            return await next_handler(request)

        request_id = current_request_id()
        if request_id:
            with sentry_sdk.isolation_scope() as scope:
                scope.set_tag("request_id", request_id)
                return await next_handler(request)
        return await next_handler(request)


# ------------------------------------------------------------ Job middleware


class SentryJobMiddleware(JobMiddleware):
    """Capture uncaught exceptions from :meth:`Job.handle` to Sentry.

    The middleware does not swallow the exception — the worker's
    retry / failure policy still runs. It only attaches the job class,
    queue, payload class name, and attempt number as structured
    context so the Sentry event is self-contained.
    """

    async def handle(
        self,
        job: Job[JobPayload],
        payload: JobPayload,
        next_call: JobMiddlewareNext,
    ) -> None:
        if not _HAS_SENTRY:
            await next_call(payload)
            return

        job_cls = type(job)
        with sentry_sdk.isolation_scope() as scope:
            scope.set_tag(
                "pylar.job.class",
                f"{job_cls.__module__}.{job_cls.__qualname__}",
            )
            scope.set_tag("pylar.job.queue", getattr(job_cls, "queue", "default"))
            scope.set_context(
                "pylar.job",
                {
                    "payload_class": type(payload).__qualname__,
                    "max_attempts": getattr(
                        job_cls, "tries", None
                    ) or getattr(job_cls, "max_attempts", None),
                },
            )
            try:
                await next_call(payload)
            except Exception as exc:
                sentry_sdk.capture_exception(exc)
                raise
