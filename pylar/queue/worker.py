"""Async worker that pulls :class:`JobRecord` instances and runs the matching job."""

from __future__ import annotations

import importlib
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager as AsyncContextManager
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from pylar.foundation.container import Container
from pylar.queue.exceptions import JobResolutionError
from pylar.queue.job import Job, JobMiddleware
from pylar.queue.payload import JobPayload
from pylar.queue.queue import JobQueue
from pylar.queue.record import JobRecord


class Worker:
    """Drive a :class:`JobQueue`, executing jobs through the container.

    The worker exposes two entry points:

    * :meth:`process_next` runs at most one job and returns. Used by
      tests, ``queue:work --once`` (later), and any caller that wants
      explicit control over the loop.
    * :meth:`run` is an infinite loop that calls :meth:`process_next`
      until :meth:`stop` is invoked. The intended caller is the
      ``queue:work`` console command.
    """

    def __init__(
        self,
        queue: JobQueue,
        container: Container,
        *,
        concurrency: int = 1,
        drain_timeout: float = 25.0,
        queues: tuple[str, ...] = ("default",),
    ) -> None:
        self._queue = queue
        self._container = container
        self._concurrency = max(1, concurrency)
        self._drain_timeout = drain_timeout
        self._queues = queues if queues else ("default",)
        self._stopping = False
        # Lifecycle hooks invoked around every job the worker
        # processes. ``queue:work`` wires them to the console
        # Output so the operator sees Horizon-style per-job lines.
        # Tests and other callers can plug in their own loggers or
        # metrics collectors. Hooks raising an exception are
        # swallowed so an observability bug never aborts a job.
        self._on_processing: list[Callable[[JobRecord], None]] = []
        self._on_processed: list[Callable[[JobRecord, float], None]] = []
        self._on_failed: list[
            Callable[[JobRecord, float, BaseException], None]
        ] = []

    def on_processing(self, hook: Callable[[JobRecord], None]) -> None:
        """Register a callback invoked before a job runs."""
        self._on_processing.append(hook)

    def on_processed(
        self, hook: Callable[[JobRecord, float], None],
    ) -> None:
        """Register a callback invoked on successful ack — duration in seconds."""
        self._on_processed.append(hook)

    def on_failed(
        self,
        hook: Callable[[JobRecord, float, BaseException], None],
    ) -> None:
        """Register a callback invoked when a job raises — duration in seconds."""
        self._on_failed.append(hook)

    @property
    def queues(self) -> tuple[str, ...]:
        """Priority list of queues this worker pops from."""
        return self._queues

    def listen_on(self, queues: tuple[str, ...]) -> None:
        """Replace the priority list of queues this worker pops from.

        Used by ``queue:work --queue=high,default,low`` to override
        whatever was bound by the service provider before
        :meth:`run` / :meth:`process_next` is called.
        """
        self._queues = queues if queues else ("default",)

    def stop(self) -> None:
        self._stopping = True

    @property
    def is_stopping(self) -> bool:
        return self._stopping

    async def run(self, *, timeout: float = 1.0) -> None:
        """Process jobs until :meth:`stop` is called.

        Registers SIGTERM and SIGINT handlers so container shutdown
        (``docker stop``, ``kill``) triggers a graceful drain: the
        worker finishes any in-flight job before exiting rather than
        abandoning it mid-execution.

        The drain phase is bounded by ``drain_timeout`` (default 25 s,
        chosen to stay under Docker/K8s default ``terminationGracePeriod``
        of 30 s). If in-flight jobs are not done by then the worker
        exits immediately — better to let the orchestrator retry the
        job than to be SIGKILLed without cleanup.

        With ``concurrency > 1`` the worker maintains *concurrency*
        in-flight ``process_next`` coroutines via ``asyncio.gather``,
        all sharing the same stop flag.
        """
        import asyncio
        import signal

        self._stopping = False

        stopped = asyncio.Event()
        original_stop = self.stop

        def _stop_with_event() -> None:
            original_stop()
            stopped.set()

        self.stop = _stop_with_event  # type: ignore[method-assign]

        # Install signal handlers *after* reassigning self.stop so
        # SIGINT / SIGTERM reach the wrapped version that also sets
        # the event — otherwise stopped.wait() would block forever
        # and Ctrl-C would appear to do nothing.
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, _stop_with_event)
            except NotImplementedError:
                pass  # Windows doesn't support add_signal_handler

        async def slot() -> None:
            while not self._stopping:
                await self.process_next(timeout=timeout)

        tasks = [asyncio.create_task(slot()) for _ in range(self._concurrency)]

        # Block until stop() is called.
        await stopped.wait()

        # Drain: let in-flight jobs finish within drain_timeout.
        # Each slot is in the middle of process_next (or about to check
        # _stopping). Give them drain_timeout seconds to wrap up.
        _, pending = await asyncio.wait(tasks, timeout=self._drain_timeout)
        for t in pending:
            t.cancel()

        self.stop = original_stop  # type: ignore[method-assign]

    async def process_next(self, *, timeout: float = 1.0) -> bool:
        """Wait for one job and run it. Returns ``True`` if a job ran, else ``False``."""
        record = await self._queue.pop(queues=self._queues, timeout=timeout)
        if record is None:
            return False
        await self._process(record)
        return True

    # ------------------------------------------------------------------ internals

    async def _process(self, record: JobRecord) -> None:
        # Resolution failures (bad module, missing attribute, payload
        # parse errors) are not retryable — the record can never succeed
        # with the same content, so we go straight to the failed pool.
        try:
            job_cls = self._resolve_job_class(record.job_class)
            payload = self._deserialize_payload(job_cls, record.payload_json)
            job = self._container.make(job_cls)
            handler = self._build_handler(job, job_cls)
        except Exception as exc:
            await self._queue.fail(record, f"{type(exc).__name__}: {exc}")
            return

        # Announce the job to observers before running it. Hooks
        # running here see the resolved job class name via
        # ``record.job_class`` — we deliberately do not pass the
        # class object so importers/transports that can't pickle
        # types still work.
        self._emit_processing(record)

        import time as _time

        started = _time.monotonic()
        policy = self._resolve_policy(record, job_cls)
        async with self._ambient_session_scope():
            try:
                if policy.timeout > 0:
                    import asyncio

                    await asyncio.wait_for(handler(payload), timeout=policy.timeout)
                else:
                    await handler(payload)
            except Exception as exc:
                elapsed = _time.monotonic() - started
                self._emit_failed(record, elapsed, exc)
                await self._handle_failure(record, job_cls, exc, policy)
                return

        elapsed = _time.monotonic() - started
        self._emit_processed(record, elapsed)
        await self._queue.ack(record)
        # Drop a recent-history entry so the admin "Recent jobs"
        # panel can show successful completions alongside failures
        # and cancellations. Drivers that don't retain history
        # (SQS, Database) no-op the call.
        try:
            await self._queue.record_completed(record, status="completed")
        except Exception:
            # History tracking is strictly best-effort — a broken
            # driver method must never abort the worker loop.
            pass

    # --------------------------------------------------------------- hooks

    def _emit_processing(self, record: JobRecord) -> None:
        for hook in self._on_processing:
            try:
                hook(record)
            except Exception:
                pass

    def _emit_processed(self, record: JobRecord, elapsed: float) -> None:
        for hook in self._on_processed:
            try:
                hook(record, elapsed)
            except Exception:
                pass

    def _emit_failed(
        self, record: JobRecord, elapsed: float, exc: BaseException,
    ) -> None:
        for hook in self._on_failed:
            try:
                hook(record, elapsed, exc)
            except Exception:
                pass

    def _resolve_policy(
        self, record: JobRecord, job_cls: type[Job[Any]]
    ) -> _EffectivePolicy:
        """Merge :class:`QueueConfig` defaults with Job-class overrides.

        Priority (most specific wins):

        1. Job class attribute (``Job.tries``, ``Job.timeout``,
           ``Job.backoff``) — set at the subclass level when a
           particular job needs policy different from its queue.
        2. Legacy ``Job.max_attempts`` — accepted as an alias for
           ``Job.tries`` so existing code keeps working.
        3. :class:`QueueConfig` for ``record.queue`` — the
           operator-controlled policy for a whole queue.
        4. :class:`QueueConfig` defaults (1 try, 60s timeout, no
           backoff) — the fallback when nothing else is bound.
        """
        from pylar.queue.config import QueueConfig, QueuesConfig

        if self._container.has(QueuesConfig):
            queue_cfg = self._container.make(QueuesConfig).for_queue(record.queue)
        else:
            queue_cfg = QueueConfig()

        tries = (
            getattr(job_cls, "tries", None)
            or getattr(job_cls, "max_attempts", None)
            or queue_cfg.tries
        )
        timeout = getattr(job_cls, "timeout", None) or queue_cfg.timeout
        backoff_attr = getattr(job_cls, "backoff", None)
        backoff: tuple[int, ...] = (
            tuple(backoff_attr) if backoff_attr else queue_cfg.backoff
        )
        return _EffectivePolicy(tries=int(tries), timeout=int(timeout), backoff=backoff)

    def _ambient_session_scope(self) -> AsyncContextManager[Any]:
        """Open an ambient DB session around the job if a manager is bound.

        User jobs use ``Post.query`` etc. directly — the worker is
        responsible for installing the session into the contextvar so
        ``current_session()`` works without any explicit setup inside
        the job itself. When the application has no database layer
        (``ConnectionManager`` not bound) this falls back to a no-op
        context, and jobs that don't touch the DB keep working.
        """
        from pylar.database.connection import ConnectionManager
        from pylar.database.session import ambient_session

        if not self._container.has(ConnectionManager):
            return _noop_scope()

        manager = self._container.make(ConnectionManager)
        return ambient_session(manager)

    def _build_handler(
        self, job: Job[Any], job_cls: type[Job[Any]]
    ) -> Callable[[JobPayload], Awaitable[None]]:
        """Compose ``job_cls.middleware`` around ``job.handle``."""

        middleware: tuple[type[JobMiddleware], ...] = tuple(
            getattr(job_cls, "middleware", ()) or ()
        )
        handler: Callable[[JobPayload], Awaitable[None]] = job.handle
        # Wrap from innermost to outermost so the declared order matches
        # request flow: middleware[0] runs first, middleware[-1] runs
        # closest to handle.
        for middleware_cls in reversed(middleware):
            instance = self._container.make(middleware_cls)
            handler = _wrap(instance, job, handler)
        return handler

    async def _handle_failure(
        self,
        record: JobRecord,
        job_cls: type[Job[Any]],
        error: Exception,
        policy: _EffectivePolicy,
    ) -> None:
        """Decide whether to retry or move *record* to the failed pool."""
        attempt = record.attempts + 1
        message = f"{type(error).__name__}: {error}"

        retry_until: timedelta | None = getattr(job_cls, "retry_until", None)
        if retry_until is not None:
            deadline = record.queued_at + retry_until
            if datetime.now(UTC) >= deadline:
                await self._queue.fail(record, message)
                return

        if attempt >= policy.tries:
            await self._queue.fail(record, message)
            return

        if policy.backoff:
            delay_seconds = policy.backoff[min(attempt - 1, len(policy.backoff) - 1)]
        else:
            delay_seconds = 0

        retry = record.model_copy(
            update={
                "attempts": attempt,
                "available_at": datetime.now(UTC) + timedelta(seconds=delay_seconds),
            }
        )
        await self._queue.push(retry)

    @staticmethod
    def _resolve_job_class(qualified_name: str) -> type[Job[Any]]:
        module_name, _, class_name = qualified_name.rpartition(".")
        if not module_name or not class_name:
            raise JobResolutionError(
                f"Job identifier {qualified_name!r} is not a fully qualified name"
            )
        try:
            module = importlib.import_module(module_name)
        except ImportError as exc:
            raise JobResolutionError(
                f"Could not import module {module_name!r} for job {qualified_name!r}: {exc}"
            ) from exc
        try:
            obj = getattr(module, class_name)
        except AttributeError as exc:
            raise JobResolutionError(
                f"Module {module_name!r} has no attribute {class_name!r}"
            ) from exc
        if not isinstance(obj, type) or not issubclass(obj, Job):
            raise JobResolutionError(
                f"{qualified_name} resolved to {obj!r}, which is not a Job subclass"
            )
        return obj

    @staticmethod
    def _deserialize_payload(job_cls: type[Job[Any]], payload_json: str) -> JobPayload:
        payload_type = getattr(job_cls, "payload_type", None)
        if payload_type is None:
            raise JobResolutionError(
                f"{job_cls.__qualname__} is missing the `payload_type` class attribute"
            )
        return cast(JobPayload, payload_type.model_validate_json(payload_json))


def _wrap(
    middleware: JobMiddleware,
    job: Job[Any],
    inner: Callable[[JobPayload], Awaitable[None]],
) -> Callable[[JobPayload], Awaitable[None]]:
    """Wrap *inner* with a single :class:`JobMiddleware`."""

    async def wrapped(payload: JobPayload) -> None:
        await middleware.handle(job, payload, inner)

    return wrapped


@asynccontextmanager
async def _noop_scope() -> AsyncIterator[None]:
    yield


@dataclass(frozen=True, slots=True)
class _EffectivePolicy:
    """Resolved per-job execution policy after merging Job + QueueConfig."""

    tries: int
    timeout: int
    backoff: tuple[int, ...]
