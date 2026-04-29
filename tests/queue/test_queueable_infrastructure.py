"""Tests for job middleware, retry_until, and concurrency."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import ClassVar

import pytest

from pylar.cache import Cache, MemoryCacheStore
from pylar.foundation.container import Container
from pylar.queue import (
    Dispatcher,
    Job,
    JobMiddleware,
    JobMiddlewareNext,
    JobPayload,
    MemoryQueue,
    RateLimited,
    WithoutOverlapping,
    Worker,
)
from pylar.queue.queue import RecentJob
from pylar.queue.record import JobRecord

# ----------------------------------------------------------- helper jobs


class _RunPayload(JobPayload):
    value: int


_seen: list[int] = []
_log: list[str] = []


class _RecordingJob(Job[_RunPayload]):
    payload_type: ClassVar[type[JobPayload]] = _RunPayload

    async def handle(self, payload: _RunPayload) -> None:
        _seen.append(payload.value)


class TraceMiddleware(JobMiddleware):
    async def handle(
        self,
        job: Job[JobPayload],
        payload: JobPayload,
        next_call: JobMiddlewareNext,
    ) -> None:
        _log.append("before")
        await next_call(payload)
        _log.append("after")


class TracedJob(Job[_RunPayload]):
    payload_type: ClassVar[type[JobPayload]] = _RunPayload
    middleware: ClassVar[tuple[type[JobMiddleware], ...]] = (TraceMiddleware,)

    async def handle(self, payload: _RunPayload) -> None:
        _log.append(f"handle:{payload.value}")


class OverlappingJob(Job[_RunPayload]):
    payload_type: ClassVar[type[JobPayload]] = _RunPayload
    middleware: ClassVar[tuple[type[JobMiddleware], ...]] = (WithoutOverlapping,)

    async def handle(self, payload: _RunPayload) -> None:
        _seen.append(payload.value)


class TightLimit(RateLimited):
    max_calls: ClassVar[int] = 2
    window_seconds: ClassVar[int] = 60


class LimitedJob(Job[_RunPayload]):
    payload_type: ClassVar[type[JobPayload]] = _RunPayload
    middleware: ClassVar[tuple[type[JobMiddleware], ...]] = (TightLimit,)

    async def handle(self, payload: _RunPayload) -> None:
        _seen.append(payload.value)


class FlakyPayload(JobPayload):
    pass


class FlakyJob(Job[FlakyPayload]):
    payload_type: ClassVar[type[JobPayload]] = FlakyPayload
    max_attempts: ClassVar[int] = 999
    retry_until: ClassVar[timedelta | None] = timedelta(seconds=-1)

    async def handle(self, payload: FlakyPayload) -> None:
        raise RuntimeError("nope")


class SlowJob(Job[_RunPayload]):
    payload_type: ClassVar[type[JobPayload]] = _RunPayload

    async def handle(self, payload: _RunPayload) -> None:
        global _in_flight, _max_seen
        _in_flight += 1
        _max_seen = max(_max_seen, _in_flight)
        _started.set()
        await asyncio.sleep(0.02)
        _in_flight -= 1


_in_flight = 0
_max_seen = 0
_started = asyncio.Event()


@pytest.fixture(autouse=True)
def _clear_seen() -> None:
    _seen.clear()
    _log.clear()
    global _in_flight, _max_seen, _started
    _in_flight = 0
    _max_seen = 0
    _started = asyncio.Event()


# ---------------------------------------------------------- middleware


async def test_middleware_runs_around_handle() -> None:
    queue = MemoryQueue()
    container = Container()
    worker = Worker(queue, container)

    await Dispatcher(queue).dispatch(TracedJob, _RunPayload(value=42))
    assert await worker.process_next(timeout=0.05) is True
    failed = await queue.failed_records()
    assert failed == [], failed[0].error if failed else ""
    assert _log == ["before", "handle:42", "after"]


async def test_without_overlapping_skips_when_lock_held() -> None:
    cache = Cache(MemoryCacheStore())
    container = Container()
    container.instance(Cache, cache)

    # Pre-grab the lock with the same key WithoutOverlapping uses.
    held = cache.lock(f"job-overlap:{OverlappingJob.__qualname__}", ttl=60)
    assert await held.acquire(blocking=False) is True

    queue = MemoryQueue()
    await Dispatcher(queue).dispatch(OverlappingJob, _RunPayload(value=1))
    worker = Worker(queue, container)
    await worker.process_next(timeout=0.05)
    assert _seen == []  # silently skipped

    await held.release()
    await Dispatcher(queue).dispatch(OverlappingJob, _RunPayload(value=2))
    await worker.process_next(timeout=0.05)
    assert _seen == [2]


async def test_rate_limited_drops_calls_above_window() -> None:
    cache = Cache(MemoryCacheStore())
    container = Container()
    container.instance(Cache, cache)

    queue = MemoryQueue()
    dispatcher = Dispatcher(queue)
    worker = Worker(queue, container)
    for i in range(5):
        await dispatcher.dispatch(LimitedJob, _RunPayload(value=i))
        await worker.process_next(timeout=0.05)

    assert _seen == [0, 1]  # 3, 4 dropped by the limit


# ---------------------------------------------------------- retry_until


async def test_retry_until_short_circuits_failed_pool() -> None:
    queue = MemoryQueue()
    container = Container()
    worker = Worker(queue, container)
    await Dispatcher(queue).dispatch(FlakyJob, FlakyPayload())

    await worker.process_next(timeout=0.05)
    failed = await queue.failed_records()
    assert len(failed) == 1


# ---------------------------------------------------------- concurrency


async def test_worker_concurrency_processes_in_parallel() -> None:
    queue = MemoryQueue()
    container = Container()

    dispatcher = Dispatcher(queue)
    for i in range(4):
        await dispatcher.dispatch(SlowJob, _RunPayload(value=i))

    worker = Worker(queue, container, concurrency=3)

    async def runner() -> None:
        await worker.run(timeout=0.05)

    task = asyncio.create_task(runner())
    await _started.wait()
    await asyncio.sleep(0.05)
    worker.stop()
    await task

    assert _max_seen >= 2  # multiple jobs running at once


# ---------------------------------------------------- Throttled middleware


class _UpstreamRateLimitError(Exception):
    """Represents the third-party API saying 429."""


class _GitHubThrottle:
    """Concrete Throttled subclass used by tests."""

    cooldown_seconds: ClassVar[int] = 60
    key_prefix: ClassVar[str] = "job-throttle"

    def __init__(self, cache: Cache) -> None:
        self._cache = cache

    async def handle(
        self,
        job: Job[JobPayload],
        payload: JobPayload,
        next_call: JobMiddlewareNext,
    ) -> None:

        # Delegate to the real Throttled's handle with _is_throttle override
        # by instantiating a concrete subclass below.
        raise NotImplementedError


from pylar.queue.middleware import Throttled  # noqa: E402


class _TestThrottle(Throttled):
    cooldown_seconds: ClassVar[int] = 60

    def _is_throttle(self, exc: BaseException) -> bool:
        return isinstance(exc, _UpstreamRateLimitError)


class _ThrottleCounter:
    """Shared counter to observe handler invocations."""

    calls = 0


_throttle_counter = _ThrottleCounter()


class _ExternalApiJob(Job[_RunPayload]):
    payload_type: ClassVar[type[JobPayload]] = _RunPayload
    middleware: ClassVar[tuple[type[JobMiddleware], ...]] = (_TestThrottle,)

    async def handle(self, payload: _RunPayload) -> None:
        _throttle_counter.calls += 1
        if payload.value == 0:
            raise _UpstreamRateLimitError("upstream said 429")


async def test_throttled_enters_cooldown_on_matching_exception() -> None:
    cache = Cache(MemoryCacheStore())
    container = Container()
    container.instance(Cache, cache)
    _throttle_counter.calls = 0

    queue = MemoryQueue()
    dispatcher = Dispatcher(queue)
    worker = Worker(queue, container)

    # First call raises → middleware records cooldown and swallows.
    await dispatcher.dispatch(_ExternalApiJob, _RunPayload(value=0))
    await worker.process_next(timeout=0.05)
    assert _throttle_counter.calls == 1

    # Second call during cooldown should short-circuit, never reaching handle.
    await dispatcher.dispatch(_ExternalApiJob, _RunPayload(value=1))
    await worker.process_next(timeout=0.05)
    assert _throttle_counter.calls == 1  # not incremented


async def test_throttled_propagates_unrelated_exceptions() -> None:
    """Non-matching exceptions must bubble up so the worker can retry/fail."""
    cache = Cache(MemoryCacheStore())
    mw = _TestThrottle(cache)

    class _OtherError(Exception):
        pass

    async def _next(payload: JobPayload) -> None:
        raise _OtherError("not a rate limit")

    class _Dummy(Job[_RunPayload]):
        payload_type: ClassVar[type[JobPayload]] = _RunPayload

        async def handle(self, payload: _RunPayload) -> None:
            return None

    with pytest.raises(_OtherError):
        await mw.handle(_Dummy(), _RunPayload(value=0), _next)


# ------------------------------------------ RateLimited on_throttled hook


class _LoggingRateLimit(RateLimited):
    max_calls: ClassVar[int] = 1
    window_seconds: ClassVar[int] = 60
    key_prefix: ClassVar[str] = "job-ratelimit-custom"
    throttled_log: ClassVar[list[int]] = []

    async def on_throttled(
        self, job: Job[JobPayload], payload: JobPayload
    ) -> None:
        assert isinstance(payload, _RunPayload)
        self.throttled_log.append(payload.value)


class _CustomLimitedJob(Job[_RunPayload]):
    payload_type: ClassVar[type[JobPayload]] = _RunPayload
    middleware: ClassVar[tuple[type[JobMiddleware], ...]] = (_LoggingRateLimit,)

    async def handle(self, payload: _RunPayload) -> None:
        _seen.append(payload.value)


async def test_rate_limited_on_throttled_hook_fires_on_overflow() -> None:
    cache = Cache(MemoryCacheStore())
    container = Container()
    container.instance(Cache, cache)
    _LoggingRateLimit.throttled_log.clear()
    _seen.clear()

    queue = MemoryQueue()
    dispatcher = Dispatcher(queue)
    worker = Worker(queue, container)

    for i in range(3):
        await dispatcher.dispatch(_CustomLimitedJob, _RunPayload(value=i))
        await worker.process_next(timeout=0.05)

    assert _seen == [0]  # only the first call ran
    assert _LoggingRateLimit.throttled_log == [1, 2]  # overflow hooks fired


# ---------------------------------------- worker lifecycle hooks


async def test_worker_emits_processing_processed_hooks() -> None:
    """Hooks fire in order: processing before run, processed after ack."""
    cache = Cache(MemoryCacheStore())
    container = Container()
    container.instance(Cache, cache)
    queue = MemoryQueue()

    events: list[tuple[str, str, float | None]] = []
    worker = Worker(queue, container)
    worker.on_processing(
        lambda rec: events.append(("processing", rec.id, None)),
    )
    worker.on_processed(
        lambda rec, elapsed: events.append(("processed", rec.id, elapsed)),
    )

    _seen.clear()
    dispatcher = Dispatcher(queue)
    await dispatcher.dispatch(_RecordingJob, _RunPayload(value=7))
    await worker.process_next(timeout=0.05)

    assert len(events) == 2
    assert events[0][0] == "processing"
    assert events[1][0] == "processed"
    assert events[0][1] == events[1][1]  # same job id
    assert events[1][2] is not None and events[1][2] >= 0


class BoomJob(Job[_RunPayload]):
    """Module-level failing job — the worker re-imports the class by
    its fully-qualified name, so local class defs fail to resolve."""

    payload_type: ClassVar[type[JobPayload]] = _RunPayload

    async def handle(self, payload: _RunPayload) -> None:
        raise RuntimeError("boom")


async def test_worker_emits_failed_hook_on_exception() -> None:
    """on_failed fires instead of on_processed when the job raises."""
    cache = Cache(MemoryCacheStore())
    container = Container()
    container.instance(Cache, cache)

    queue = MemoryQueue()
    worker = Worker(queue, container)
    calls: list[str] = []
    worker.on_processed(lambda rec, elapsed: calls.append("processed"))
    worker.on_failed(lambda rec, elapsed, exc: calls.append(f"failed:{exc}"))

    await Dispatcher(queue).dispatch(BoomJob, _RunPayload(value=1))
    await worker.process_next(timeout=0.05)

    assert calls == ["failed:boom"]


async def test_failing_hook_does_not_abort_job() -> None:
    """Exceptions inside hooks are swallowed so a buggy observer
    never breaks the worker."""
    cache = Cache(MemoryCacheStore())
    container = Container()
    container.instance(Cache, cache)

    queue = MemoryQueue()
    worker = Worker(queue, container)
    worker.on_processing(lambda rec: (_ for _ in ()).throw(RuntimeError("noisy hook")))

    _seen.clear()
    await Dispatcher(queue).dispatch(_RecordingJob, _RunPayload(value=99))
    await worker.process_next(timeout=0.05)

    assert _seen == [99]  # job still ran despite noisy hook


# ----------------------------------------- recent-history pool


async def test_worker_records_completed_jobs_in_recent_pool() -> None:
    """After ack, the job surfaces on recent_records with status=completed."""
    cache = Cache(MemoryCacheStore())
    container = Container()
    container.instance(Cache, cache)
    queue = MemoryQueue()
    worker = Worker(queue, container)

    _seen.clear()
    await Dispatcher(queue).dispatch(_RecordingJob, _RunPayload(value=11))
    await worker.process_next(timeout=0.05)

    recent = await queue.recent_records("default")
    assert len(recent) == 1
    assert recent[0].status == "completed"
    assert recent[0].record.queue == "default"


async def test_failed_jobs_also_land_in_recent_pool() -> None:
    """fail() dual-writes into failed + recent pools."""
    cache = Cache(MemoryCacheStore())
    container = Container()
    container.instance(Cache, cache)
    queue = MemoryQueue()
    worker = Worker(queue, container)

    await Dispatcher(queue).dispatch(BoomJob, _RunPayload(value=0))
    await worker.process_next(timeout=0.05)

    recent = await queue.recent_records("default")
    assert len(recent) == 1
    assert recent[0].status == "failed"
    assert recent[0].error is not None and "boom" in recent[0].error


async def test_recent_retention_drops_old_entries() -> None:
    """Entries older than ``recent_retention_seconds`` are pruned on read."""
    from datetime import timedelta

    queue = MemoryQueue(recent_retention_seconds=1)
    fresh = JobRecord(id="a", job_class="x:X", payload_json="{}")
    await queue.record_completed(fresh, status="completed")
    # Mutate the stored entry to look old.
    bucket = queue._recent["default"]
    bucket[0] = RecentJob(
        record=bucket[0].record,
        status=bucket[0].status,
        completed_at=bucket[0].completed_at - timedelta(seconds=5),
        error=bucket[0].error,
    )

    assert await queue.recent_records("default") == []


async def test_cancelled_status_can_be_recorded_directly() -> None:
    queue = MemoryQueue()
    rec = JobRecord(id="c", job_class="x:X", payload_json="{}")
    await queue.record_completed(rec, status="cancelled")
    [entry] = await queue.recent_records("default")
    assert entry.status == "cancelled"
