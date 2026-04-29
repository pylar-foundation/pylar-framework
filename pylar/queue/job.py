"""The :class:`Job` base class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import ClassVar

from pylar.queue.exceptions import JobDefinitionError
from pylar.queue.payload import JobPayload


class Job[PayloadT: JobPayload](ABC):
    """A typed background job.

    Subclasses declare a ``payload_type`` class attribute pointing at a
    :class:`JobPayload` subclass. The framework uses that type for both
    serialisation (dispatcher → queue) and deserialisation (worker →
    handle). The ``handle`` method receives the typed payload and should
    raise on any unrecoverable failure — the worker reports it via the
    retry policy below.

    Constructor arguments are auto-wired by the container, so a job can
    declare any service dependencies it needs at execution time.

    Retry policy
    ------------

    ``max_attempts`` is the total number of times a single record may be
    handed to ``handle`` before the worker gives up and moves it to the
    failed pool. ``backoff`` is the sequence of seconds to wait between
    successive attempts; the worker uses ``backoff[attempt - 1]`` and
    falls back to the last entry once the sequence is exhausted.

    Default: one attempt, no backoff (matches the original behaviour).
    Override on the subclass to opt into retries::

        class SendWelcomeJob(Job[SendWelcomePayload]):
            payload_type = SendWelcomePayload
            max_attempts = 5
            backoff = (5, 30, 120, 300, 600)
    """

    payload_type: ClassVar[type[JobPayload]]

    #: Default queue name for instances of this job. Dispatch-time
    #: ``queue=`` overrides this. Matches Laravel's ``public $queue``.
    queue: ClassVar[str] = "default"

    #: Total attempts before the job moves to the failed pool. ``1``
    #: means "no retries" — the worker tries once, then either acks or
    #: fails. ``None`` (the default) defers to the queue's
    #: :class:`QueueConfig.tries`. Matches Laravel ``public $tries``.
    #: The legacy name ``max_attempts`` remains accepted for
    #: backwards-compat with code written before the queue-config
    #: layer landed.
    tries: ClassVar[int | None] = None
    max_attempts: ClassVar[int | None] = None

    #: Per-job timeout in seconds. ``None`` defers to the queue's
    #: :class:`QueueConfig.timeout`. Matches Laravel ``public $timeout``.
    timeout: ClassVar[int | None] = None

    #: Seconds to wait between attempts. ``backoff[attempt - 1]`` is the
    #: delay applied *before* the next try. The last entry is reused for
    #: any further attempts. An empty tuple means "retry immediately".
    #: ``None`` defers to the queue's :class:`QueueConfig.backoff`.
    backoff: ClassVar[tuple[int, ...] | None] = None

    #: Wall-clock deadline for retries, measured from the *original*
    #: ``queued_at`` timestamp. Once the deadline is reached the worker
    #: stops retrying even if ``max_attempts`` has not been exhausted.
    #: ``None`` means "no deadline" (the default).
    retry_until: ClassVar[timedelta | None] = None

    #: Optional list of middleware applied around :meth:`handle`. Each
    #: entry is a callable that takes (job, payload, next) and may
    #: short-circuit, instrument, or fail the call. The :class:`Worker`
    #: composes them in declaration order with ``handle`` as the
    #: innermost layer.
    middleware: ClassVar[tuple[type[JobMiddleware], ...]] = ()

    @abstractmethod
    async def handle(self, payload: PayloadT) -> None:
        """Run the job. Raise to mark the dispatch as failed."""

    @classmethod
    def _validate_definition(cls) -> None:
        if not hasattr(cls, "payload_type"):
            raise JobDefinitionError(
                f"{cls.__qualname__} must define a `payload_type` class attribute"
            )


class JobMiddleware(ABC):
    """Base class for job middleware.

    Subclasses receive their dependencies through ``__init__`` (the
    container builds them) and override :meth:`handle` to wrap the
    inner call. Cross-cutting concerns — rate limiting, distributed
    overlap protection, throttling around third-party APIs — fit here
    naturally and stay out of the job body.

    The contract mirrors the HTTP middleware Pipeline:

        async def handle(self, job, payload, next):
            # before
            await next(payload)
            # after

    Middleware that wants to skip the call (rate limit hit, lock not
    acquired) simply returns without invoking ``next``.
    """

    @abstractmethod
    async def handle(
        self,
        job: Job[JobPayload],
        payload: JobPayload,
        next_call: JobMiddlewareNext,
    ) -> None: ...


JobMiddlewareNext = Callable[[JobPayload], Awaitable[None]]
