"""The typed entry point that controllers call to enqueue jobs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar
from uuid import uuid4

from pylar.queue.job import Job
from pylar.queue.payload import JobPayload
from pylar.queue.queue import JobQueue
from pylar.queue.record import JobRecord

PayloadT = TypeVar("PayloadT", bound=JobPayload)


class Dispatcher:
    """Push :class:`Job` instances onto the bound :class:`JobQueue`.

    Resolved through the container; controllers, services, and other jobs
    declare ``dispatcher: Dispatcher`` in their ``__init__`` and call
    :meth:`dispatch` with a job class plus a typed payload. The dispatcher
    serialises the payload, builds a :class:`JobRecord`, and hands it to
    the queue driver.

    The job class is identified on the wire by its fully qualified name
    (``module.ClassName``) so that a worker process — even one running on
    a different machine — can resolve and instantiate it.

    Pass ``delay`` to defer execution: the dispatcher records
    ``available_at = now() + delay`` and the queue driver respects the
    field on pop. ``MemoryQueue`` simulates the wait by sleeping until
    the record is ready; persistent drivers (database, Redis) compare
    the timestamp during their normal pop query.
    """

    def __init__(self, queue: JobQueue) -> None:
        self._queue = queue

    async def dispatch(
        self,
        job_cls: type[Job[PayloadT]],
        payload: PayloadT,
        *,
        delay: timedelta | None = None,
        queue: str | None = None,
    ) -> JobRecord:
        now = datetime.now(UTC)
        available_at = now + delay if delay is not None else now
        record = JobRecord(
            id=str(uuid4()),
            job_class=f"{job_cls.__module__}.{job_cls.__qualname__}",
            payload_json=payload.model_dump_json(),
            queue=queue if queue is not None else getattr(job_cls, "queue", "default"),
            queued_at=now,
            available_at=available_at,
        )
        await self._queue.push(record)
        return record

    @staticmethod
    def fake() -> FakeDispatcher:
        """Return a recording :class:`FakeDispatcher` for tests.

        The fake captures every dispatch in memory and exposes
        ``dispatched`` / ``assert_dispatched`` / ``assert_not_dispatched``
        helpers so test code can assert intent without standing up a
        real queue or worker.
        """
        return FakeDispatcher()


class FakeDispatcher:
    """In-memory recording dispatcher used by tests.

    Drop-in for :class:`Dispatcher` — controllers under test that
    declare ``dispatcher: Dispatcher`` in their ``__init__`` accept the
    fake without changes when the test binds it via
    ``container.instance(Dispatcher, Dispatcher.fake())``.
    """

    def __init__(self) -> None:
        self._calls: list[tuple[type[Job[Any]], JobPayload, timedelta | None, str]] = []

    async def dispatch(
        self,
        job_cls: type[Job[PayloadT]],
        payload: PayloadT,
        *,
        delay: timedelta | None = None,
        queue: str | None = None,
    ) -> JobRecord:
        resolved_queue = queue if queue is not None else getattr(job_cls, "queue", "default")
        self._calls.append((job_cls, payload, delay, resolved_queue))
        now = datetime.now(UTC)
        return JobRecord(
            id=str(uuid4()),
            job_class=f"{job_cls.__module__}.{job_cls.__qualname__}",
            payload_json=payload.model_dump_json(),
            queue=resolved_queue,
            queued_at=now,
            available_at=now + delay if delay is not None else now,
        )

    # ----------------------------------------------------------- inspection

    def dispatched(
        self, job_cls: type[Job[Any]] | None = None
    ) -> list[JobPayload]:
        """Return every recorded payload, optionally filtered by job class."""
        if job_cls is None:
            return [payload for _, payload, _, _ in self._calls]
        return [
            payload
            for cls, payload, _, _ in self._calls
            if cls is job_cls
        ]

    def assert_dispatched(
        self,
        job_cls: type[Job[Any]],
        times: int | None = None,
    ) -> None:
        """Assert *job_cls* was dispatched at least once (or *times* times)."""
        matches = [cls for cls, _, _, _ in self._calls if cls is job_cls]
        if times is None:
            if not matches:
                raise AssertionError(
                    f"Expected {job_cls.__qualname__} to have been dispatched, "
                    f"but no matching call was recorded"
                )
            return
        if len(matches) != times:
            raise AssertionError(
                f"Expected {job_cls.__qualname__} to have been dispatched "
                f"{times} time(s), got {len(matches)}"
            )

    def assert_not_dispatched(self, job_cls: type[Job[Any]]) -> None:
        """Assert *job_cls* was never dispatched."""
        matches = [cls for cls, _, _, _ in self._calls if cls is job_cls]
        if matches:
            raise AssertionError(
                f"Expected {job_cls.__qualname__} not to have been dispatched, "
                f"got {len(matches)} call(s)"
            )

    def clear(self) -> None:
        self._calls.clear()
