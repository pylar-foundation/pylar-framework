"""Tests for the queue production-ready batch.

Covers retry policy, delayed dispatch, failed-jobs storage with the
``queue:failed`` and ``queue:retry`` commands, and the recording
``Dispatcher.fake()`` test fake.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from pylar.foundation import Container
from pylar.queue import (
    Dispatcher,
    Job,
    JobPayload,
    MemoryQueue,
    Worker,
)
from pylar.queue.commands import (
    QueueFailedCommand,
    QueueRetryCommand,
    QueueRetryInput,
    _QueueFailedInput,
)

# --------------------------------------------------------------------- domain


class _Recorder:
    def __init__(self) -> None:
        self.attempts: list[int] = []
        self.flaky_until: int = 0  # raise on first N attempts

    async def run(self, attempt: int) -> None:
        self.attempts.append(attempt)
        if attempt <= self.flaky_until:
            raise RuntimeError(f"flake on attempt {attempt}")


class FlakyPayload(JobPayload):
    label: str


class FlakyJob(Job[FlakyPayload]):
    """Reads ``_Recorder`` from the container so the test can drive failures."""

    payload_type = FlakyPayload
    max_attempts = 3
    backoff = (0, 0)  # immediate retries to keep the test fast

    def __init__(self, recorder: _Recorder) -> None:
        self.recorder = recorder

    async def handle(self, payload: FlakyPayload) -> None:
        await self.recorder.run(len(self.recorder.attempts) + 1)


class AlwaysFailJob(Job[FlakyPayload]):
    """A job that fails on every attempt regardless of the recorder state."""

    payload_type = FlakyPayload
    max_attempts = 2
    backoff = (0,)

    def __init__(self, recorder: _Recorder) -> None:
        self.recorder = recorder

    async def handle(self, payload: FlakyPayload) -> None:
        self.recorder.attempts.append(len(self.recorder.attempts) + 1)
        raise RuntimeError("permanent failure")


class SimplePayload(JobPayload):
    name: str


class SimpleJob(Job[SimplePayload]):
    payload_type = SimplePayload

    def __init__(self, recorder: _Recorder) -> None:
        self.recorder = recorder

    async def handle(self, payload: SimplePayload) -> None:
        self.recorder.attempts.append(0)


# ----------------------------------------------------------------- fixtures


@pytest.fixture
def container() -> Container:
    container = Container()
    container.instance(_Recorder, _Recorder())
    return container


@pytest.fixture
def queue() -> MemoryQueue:
    return MemoryQueue()


@pytest.fixture
def dispatcher(queue: MemoryQueue) -> Dispatcher:
    return Dispatcher(queue)


@pytest.fixture
def worker(queue: MemoryQueue, container: Container) -> Worker:
    return Worker(queue, container)


# ----------------------------------------------------------------- retry


async def test_retry_succeeds_within_max_attempts(
    dispatcher: Dispatcher,
    worker: Worker,
    container: Container,
    queue: MemoryQueue,
) -> None:
    recorder = container.make(_Recorder)
    recorder.flaky_until = 2  # fail attempts 1+2, succeed on 3

    await dispatcher.dispatch(FlakyJob, FlakyPayload(label="x"))

    # Three attempts → first two re-queue, third acks.
    for _ in range(3):
        ran = await worker.process_next(timeout=0.5)
        assert ran is True

    assert recorder.attempts == [1, 2, 3]
    assert len(queue.acked) == 1
    assert queue.failed == []


async def test_retry_exhausts_and_marks_failed(
    dispatcher: Dispatcher,
    worker: Worker,
    container: Container,
    queue: MemoryQueue,
) -> None:
    recorder = container.make(_Recorder)

    await dispatcher.dispatch(AlwaysFailJob, FlakyPayload(label="boom"))

    # max_attempts=2 → first try re-queues, second moves to failed.
    for _ in range(2):
        await worker.process_next(timeout=0.5)

    assert len(recorder.attempts) == 2
    failed = await queue.failed_records()
    assert len(failed) == 1
    assert "permanent failure" in failed[0].error
    assert failed[0].record.attempts == 1  # advanced once before fail


async def test_retry_attempts_field_increments_per_retry(
    dispatcher: Dispatcher,
    worker: Worker,
    container: Container,
    queue: MemoryQueue,
) -> None:
    container.make(_Recorder).flaky_until = 1  # fail once, succeed second

    record = await dispatcher.dispatch(FlakyJob, FlakyPayload(label="r"))
    assert record.attempts == 0

    await worker.process_next(timeout=0.5)  # try 1, fails, re-queue

    # The re-queued copy now has attempts == 1.
    requeued_records = [
        item[2]
        for heap in queue._heaps.values()  # type: ignore[attr-defined]
        for item in heap
    ]
    assert len(requeued_records) == 1
    assert requeued_records[0].attempts == 1
    assert requeued_records[0].id == record.id

    await worker.process_next(timeout=0.5)  # try 2, succeeds
    assert len(queue.acked) == 1


# ----------------------------------------------------------------- delay


async def test_delayed_dispatch_does_not_pop_immediately(
    dispatcher: Dispatcher,
    worker: Worker,
    container: Container,
) -> None:
    recorder = container.make(_Recorder)

    await dispatcher.dispatch(
        SimpleJob, SimplePayload(name="later"), delay=timedelta(seconds=10)
    )

    # The record sits in the heap but is not yet due — pop times out.
    ran = await worker.process_next(timeout=0.05)
    assert ran is False
    assert recorder.attempts == []


async def test_delayed_dispatch_runs_after_delay(
    dispatcher: Dispatcher,
    worker: Worker,
    container: Container,
) -> None:
    recorder = container.make(_Recorder)

    await dispatcher.dispatch(
        SimpleJob, SimplePayload(name="soon"), delay=timedelta(milliseconds=100)
    )

    # First pop within the delay window times out.
    ran = await worker.process_next(timeout=0.05)
    assert ran is False
    assert recorder.attempts == []

    # Wait for the record to become due, then pop again.
    await asyncio.sleep(0.12)
    ran = await worker.process_next(timeout=0.2)
    assert ran is True
    assert recorder.attempts == [0]


async def test_immediate_dispatch_pops_right_away(
    dispatcher: Dispatcher,
    worker: Worker,
    container: Container,
) -> None:
    recorder = container.make(_Recorder)
    await dispatcher.dispatch(SimpleJob, SimplePayload(name="now"))

    ran = await worker.process_next(timeout=0.05)
    assert ran is True
    assert recorder.attempts == [0]


# ----------------------------------------------------------- failed pool


async def test_failed_records_returns_failed_job(
    dispatcher: Dispatcher,
    worker: Worker,
    queue: MemoryQueue,
) -> None:
    await dispatcher.dispatch(AlwaysFailJob, FlakyPayload(label="x"))
    for _ in range(2):
        await worker.process_next(timeout=0.5)

    failed = await queue.failed_records()
    assert len(failed) == 1
    entry = failed[0]
    assert entry.record.job_class.endswith("AlwaysFailJob")
    assert "permanent failure" in entry.error


async def test_retry_failed_moves_record_back(
    dispatcher: Dispatcher,
    worker: Worker,
    queue: MemoryQueue,
    container: Container,
) -> None:
    container.make(_Recorder).flaky_until = 99  # always fail
    await dispatcher.dispatch(AlwaysFailJob, FlakyPayload(label="rip"))
    for _ in range(2):
        await worker.process_next(timeout=0.5)
    assert len(await queue.failed_records()) == 1

    moved = await queue.retry_failed()
    assert moved == 1
    assert len(await queue.failed_records()) == 0
    assert queue.qsize() == 1


# --------------------------------------------------- queue:failed command


async def test_queue_failed_command_lists_pool(
    dispatcher: Dispatcher,
    worker: Worker,
    queue: MemoryQueue,
) -> None:
    from io import StringIO

    from pylar.console.output import Output

    await dispatcher.dispatch(AlwaysFailJob, FlakyPayload(label="dead"))
    for _ in range(2):
        await worker.process_next(timeout=0.5)

    buf = StringIO()
    cmd = QueueFailedCommand(queue, Output(buf, colour=False))
    code = await cmd.handle(_QueueFailedInput())
    assert code == 0
    out = buf.getvalue()
    assert "AlwaysFailJob" in out
    assert "1 failed job" in out


async def test_queue_failed_command_empty(queue: MemoryQueue) -> None:
    from io import StringIO

    from pylar.console.output import Output

    buf = StringIO()
    cmd = QueueFailedCommand(queue, Output(buf, colour=False))
    await cmd.handle(_QueueFailedInput())
    assert "No failed jobs" in buf.getvalue()


async def test_queue_retry_command_moves_everything(
    dispatcher: Dispatcher,
    worker: Worker,
    queue: MemoryQueue,
) -> None:
    from io import StringIO

    from pylar.console.output import Output

    await dispatcher.dispatch(AlwaysFailJob, FlakyPayload(label="dead"))
    for _ in range(2):
        await worker.process_next(timeout=0.5)

    buf = StringIO()
    cmd = QueueRetryCommand(queue, Output(buf, colour=False))
    code = await cmd.handle(QueueRetryInput())
    assert code == 0
    assert "Re-queued 1" in buf.getvalue()
    assert queue.qsize() == 1


async def test_queue_retry_command_specific_id(
    dispatcher: Dispatcher,
    worker: Worker,
    queue: MemoryQueue,
) -> None:
    from io import StringIO

    from pylar.console.output import Output

    record = await dispatcher.dispatch(AlwaysFailJob, FlakyPayload(label="x"))
    for _ in range(2):
        await worker.process_next(timeout=0.5)
    failed = await queue.failed_records()
    assert len(failed) == 1
    target_id = failed[0].record.id

    buf = StringIO()
    cmd = QueueRetryCommand(queue, Output(buf, colour=False))
    moved = await cmd.handle(QueueRetryInput(record_id=target_id))
    assert moved == 0  # exit code, not the count
    assert queue.qsize() == 1
    assert len(await queue.failed_records()) == 0
    # Re-queued record kept its id.
    assert record.id == target_id


# ----------------------------------------------------------- FakeDispatcher


async def test_fake_dispatcher_records_calls() -> None:
    fake = Dispatcher.fake()
    await fake.dispatch(SimpleJob, SimplePayload(name="alice"))
    await fake.dispatch(SimpleJob, SimplePayload(name="bob"))
    await fake.dispatch(FlakyJob, FlakyPayload(label="x"))

    fake.assert_dispatched(SimpleJob, times=2)
    fake.assert_dispatched(FlakyJob)
    fake.assert_not_dispatched(AlwaysFailJob)


async def test_fake_dispatcher_dispatched_returns_payloads() -> None:
    fake = Dispatcher.fake()
    await fake.dispatch(SimpleJob, SimplePayload(name="alice"))
    await fake.dispatch(SimpleJob, SimplePayload(name="bob"))

    payloads = fake.dispatched(SimpleJob)
    assert len(payloads) == 2
    assert {p.name for p in payloads} == {"alice", "bob"}  # type: ignore[attr-defined]


async def test_fake_dispatcher_assert_failures() -> None:
    fake = Dispatcher.fake()

    with pytest.raises(AssertionError, match="Expected"):
        fake.assert_dispatched(SimpleJob)

    await fake.dispatch(SimpleJob, SimplePayload(name="x"))
    with pytest.raises(AssertionError, match="not to have been dispatched"):
        fake.assert_not_dispatched(SimpleJob)


async def test_fake_dispatcher_clear() -> None:
    fake = Dispatcher.fake()
    await fake.dispatch(SimpleJob, SimplePayload(name="x"))
    fake.clear()
    fake.assert_not_dispatched(SimpleJob)


# ---------------------------------------- queue:run / forget / flush / clear / prune


async def test_queue_run_processes_single_job(
    dispatcher: Dispatcher, worker: Worker, queue: MemoryQueue
) -> None:
    from io import StringIO

    from pylar.console.output import Output
    from pylar.queue.commands import QueueRunCommand, _QueueRunInput

    await dispatcher.dispatch(SimpleJob, SimplePayload(name="alice"))
    assert queue.qsize() == 1

    buf = StringIO()
    cmd = QueueRunCommand(worker, Output(buf, colour=False))
    code = await cmd.handle(_QueueRunInput())
    assert code == 0
    assert "Processed 1 job" in buf.getvalue()
    assert queue.qsize() == 0


async def test_queue_run_reports_empty_queue(
    worker: Worker, queue: MemoryQueue
) -> None:
    from io import StringIO

    from pylar.console.output import Output
    from pylar.queue.commands import QueueRunCommand, _QueueRunInput

    buf = StringIO()
    cmd = QueueRunCommand(worker, Output(buf, colour=False))
    code = await cmd.handle(_QueueRunInput())
    assert code == 0
    assert "No job available" in buf.getvalue()


async def test_queue_forget_deletes_single_failed(
    dispatcher: Dispatcher, worker: Worker, queue: MemoryQueue
) -> None:
    from io import StringIO

    from pylar.console.output import Output
    from pylar.queue.commands import QueueForgetCommand, _QueueForgetInput

    record = await dispatcher.dispatch(AlwaysFailJob, FlakyPayload(label="x"))
    for _ in range(2):
        await worker.process_next(timeout=0.5)

    buf = StringIO()
    cmd = QueueForgetCommand(queue, Output(buf, colour=False))
    code = await cmd.handle(_QueueForgetInput(record_id=record.id))
    assert code == 0
    assert "Deleted" in buf.getvalue()
    assert len(await queue.failed_records()) == 0


async def test_queue_forget_unknown_id_errors(queue: MemoryQueue) -> None:
    from io import StringIO

    from pylar.console.output import Output
    from pylar.queue.commands import QueueForgetCommand, _QueueForgetInput

    buf = StringIO()
    cmd = QueueForgetCommand(queue, Output(buf, colour=False))
    code = await cmd.handle(_QueueForgetInput(record_id="missing"))
    assert code == 1
    assert "No failed job" in buf.getvalue()


async def test_queue_flush_clears_failed_pool(
    dispatcher: Dispatcher, worker: Worker, queue: MemoryQueue
) -> None:
    from io import StringIO

    from pylar.console.output import Output
    from pylar.queue.commands import QueueFlushCommand, _QueueFlushInput

    await dispatcher.dispatch(AlwaysFailJob, FlakyPayload(label="a"))
    await dispatcher.dispatch(AlwaysFailJob, FlakyPayload(label="b"))
    for _ in range(4):
        await worker.process_next(timeout=0.5)
    assert len(await queue.failed_records()) == 2

    buf = StringIO()
    cmd = QueueFlushCommand(queue, Output(buf, colour=False))
    code = await cmd.handle(_QueueFlushInput(force=True))
    assert code == 0
    assert "Flushed 2" in buf.getvalue()
    assert len(await queue.failed_records()) == 0


async def test_queue_clear_empties_pending_queue(
    dispatcher: Dispatcher, queue: MemoryQueue
) -> None:
    from io import StringIO

    from pylar.console.output import Output
    from pylar.queue.commands import QueueClearCommand, _QueueClearInput

    await dispatcher.dispatch(SimpleJob, SimplePayload(name="a"))
    await dispatcher.dispatch(SimpleJob, SimplePayload(name="b"))
    assert queue.qsize() == 2

    buf = StringIO()
    cmd = QueueClearCommand(queue, Output(buf, colour=False))
    code = await cmd.handle(_QueueClearInput(force=True))
    assert code == 0
    assert "Cleared 2" in buf.getvalue()
    assert queue.qsize() == 0


async def test_queue_prune_failed_drops_old_records(
    dispatcher: Dispatcher, worker: Worker, queue: MemoryQueue
) -> None:
    from datetime import UTC, datetime, timedelta
    from io import StringIO

    from pylar.console.output import Output
    from pylar.queue.commands import (
        QueuePruneFailedCommand,
        _QueuePruneFailedInput,
    )
    from pylar.queue.queue import FailedJob

    await dispatcher.dispatch(AlwaysFailJob, FlakyPayload(label="old"))
    for _ in range(2):
        await worker.process_next(timeout=0.5)
    failed = await queue.failed_records()
    assert len(failed) == 1

    # Rewind the in-memory failed_at by 48h so prune --hours=24 trims it.
    target_id = failed[0].record.id
    old = datetime.now(UTC) - timedelta(hours=48)
    queue._failed[target_id] = FailedJob(
        record=failed[0].record, error=failed[0].error, failed_at=old,
    )

    buf = StringIO()
    cmd = QueuePruneFailedCommand(queue, Output(buf, colour=False))
    code = await cmd.handle(_QueuePruneFailedInput(hours=24))
    assert code == 0
    assert "Pruned 1" in buf.getvalue()
    assert len(await queue.failed_records()) == 0


# ----------------------------------------------------- named queues + priority


class HighQueueJob(Job[SimplePayload]):
    payload_type = SimplePayload
    queue = "high"

    def __init__(self) -> None:
        pass

    async def handle(self, payload: SimplePayload) -> None:
        pass


async def test_dispatch_uses_job_class_queue_attribute(
    dispatcher: Dispatcher, queue: MemoryQueue
) -> None:
    record = await dispatcher.dispatch(HighQueueJob, SimplePayload(name="a"))
    assert record.queue == "high"
    assert await queue.size("high") == 1
    assert await queue.size("default") == 0


async def test_dispatch_queue_kwarg_overrides_class_default(
    dispatcher: Dispatcher, queue: MemoryQueue
) -> None:
    record = await dispatcher.dispatch(
        HighQueueJob, SimplePayload(name="a"), queue="low"
    )
    assert record.queue == "low"
    assert await queue.size("low") == 1
    assert await queue.size("high") == 0


async def test_pop_walks_priority_list_left_to_right(queue: MemoryQueue) -> None:
    from pylar.queue.record import JobRecord

    await queue.push(JobRecord(
        id="low-1", job_class="x.Y", payload_json="{}", queue="low",
    ))
    await queue.push(JobRecord(
        id="high-1", job_class="x.Y", payload_json="{}", queue="high",
    ))
    await queue.push(JobRecord(
        id="default-1", job_class="x.Y", payload_json="{}", queue="default",
    ))

    first = await queue.pop(queues=("high", "default", "low"), timeout=0.1)
    assert first is not None and first.id == "high-1"

    second = await queue.pop(queues=("high", "default", "low"), timeout=0.1)
    assert second is not None and second.id == "default-1"

    third = await queue.pop(queues=("high", "default", "low"), timeout=0.1)
    assert third is not None and third.id == "low-1"


async def test_pop_ignores_queues_not_in_priority_list(queue: MemoryQueue) -> None:
    from pylar.queue.record import JobRecord

    await queue.push(JobRecord(
        id="low-1", job_class="x.Y", payload_json="{}", queue="low",
    ))
    # Asking only for "high" should time out — there's nothing on "high".
    miss = await queue.pop(queues=("high",), timeout=0.05)
    assert miss is None


def test_parse_queues_helper() -> None:
    from pylar.queue.commands import _parse_queues

    assert _parse_queues("high,default,low") == ("high", "default", "low")
    assert _parse_queues("  high , default ") == ("high", "default")
    assert _parse_queues("") == ("default",)
    assert _parse_queues(",,,") == ("default",)


# --------------------------------------------- queue config (phase 2)


class _ExplodingRecorder(_Recorder):
    """Recorder variant that always raises — keeps fail path simple."""

    async def run(self, attempt: int) -> None:  # type: ignore[override]
        self.attempts.append(attempt)
        raise RuntimeError(f"boom on attempt {attempt}")


class _BareJob(Job[SimplePayload]):
    """A job with no class-level policy — picks up the queue config."""

    payload_type = SimplePayload
    queue = "bursty"

    def __init__(self, recorder: _Recorder) -> None:
        self.recorder = recorder

    async def handle(self, payload: SimplePayload) -> None:
        await self.recorder.run(len(self.recorder.attempts) + 1)


class _PinnedTriesJob(_BareJob):
    """Class-level ``tries=2`` pin should beat the queue's ``tries=10``."""

    tries = 2


class _SlowJob(Job[SimplePayload]):
    """A job that sleeps past the queue timeout so wait_for trips."""

    payload_type = SimplePayload
    queue = "slow"

    def __init__(self) -> None:
        pass

    async def handle(self, payload: SimplePayload) -> None:
        import asyncio

        await asyncio.sleep(1.0)


async def test_worker_honours_queue_config_tries_and_backoff(
    queue: MemoryQueue, container: Container
) -> None:
    from pylar.queue import QueueConfig, QueuesConfig

    container.instance(QueuesConfig, QueuesConfig(queues={
        "bursty": QueueConfig(tries=3, timeout=5, backoff=()),
    }))
    container.instance(_Recorder, _ExplodingRecorder())
    worker = Worker(queue, container, queues=("bursty",))

    dispatcher = Dispatcher(queue)
    await dispatcher.dispatch(_BareJob, SimplePayload(name="x"))

    # 3 tries total from the queue config, then a failed record.
    for _ in range(3):
        await worker.process_next(timeout=0.2)

    assert len(await queue.failed_records()) == 1
    recorder: _ExplodingRecorder = container.make(_Recorder)  # type: ignore[assignment]
    assert len(recorder.attempts) == 3


async def test_job_class_overrides_queue_config(
    queue: MemoryQueue, container: Container
) -> None:
    from pylar.queue import QueueConfig, QueuesConfig

    container.instance(QueuesConfig, QueuesConfig(queues={
        "bursty": QueueConfig(tries=10),  # queue would allow 10 ...
    }))

    container.instance(_Recorder, _ExplodingRecorder())
    worker = Worker(queue, container, queues=("bursty",))

    dispatcher = Dispatcher(queue)
    record = await dispatcher.dispatch(_PinnedTriesJob, SimplePayload(name="x"))
    assert record.queue == "bursty"

    await worker.process_next(timeout=0.5)
    await worker.process_next(timeout=0.5)

    recorder: _ExplodingRecorder = container.make(_Recorder)  # type: ignore[assignment]
    assert len(recorder.attempts) == 2
    assert len(await queue.failed_records()) == 1


async def test_queue_timeout_moves_to_failed(
    queue: MemoryQueue, container: Container
) -> None:
    from pylar.queue import QueueConfig, QueuesConfig

    container.instance(QueuesConfig, QueuesConfig(queues={
        "slow": QueueConfig(tries=1, timeout=1),
    }))
    worker = Worker(queue, container, queues=("slow",))

    dispatcher = Dispatcher(queue)
    await dispatcher.dispatch(_SlowJob, SimplePayload(name="s"))

    await worker.process_next(timeout=0.1)
    failed = await queue.failed_records()
    assert len(failed) == 1
    assert "TimeoutError" in failed[0].error or "Timeout" in failed[0].error


def test_queues_config_defaults_cover_high_default_low() -> None:
    from pylar.queue import DEFAULT_QUEUES, QueuesConfig

    cfg = QueuesConfig()
    assert set(cfg.names()) >= {"high", "default", "low"}
    assert cfg.for_queue("high").tries >= 1
    # Unknown queue falls back.
    assert cfg.for_queue("nonexistent").tries == cfg.fallback.tries
    assert DEFAULT_QUEUES["high"].tries == 5


# ------------------------------------------------------- supervisor (phase 3)


class _SupervisorTestPayload(JobPayload):
    label: str


class _SupervisorTestJob(Job[_SupervisorTestPayload]):
    payload_type = _SupervisorTestPayload
    queue = "default"

    def __init__(self) -> None:
        pass

    async def handle(self, payload: _SupervisorTestPayload) -> None:
        # Hold the worker long enough that the supervisor sees backlog
        # build up before any single worker drains it.
        import asyncio

        await asyncio.sleep(0.5)


async def test_supervisor_starts_min_workers_per_queue(
    queue: MemoryQueue, container: Container
) -> None:
    import asyncio

    from pylar.queue import QueueConfig, QueuesConfig, QueueSupervisor

    cfg = QueuesConfig(queues={
        "high": QueueConfig(min_workers=2, max_workers=4),
        "default": QueueConfig(min_workers=1, max_workers=3),
    })
    sup = QueueSupervisor(queue, container, cfg, poll_seconds=0.05)

    task = asyncio.create_task(sup.run())
    await asyncio.sleep(0.15)
    sizes = sup.pool_sizes()
    assert sizes == {"high": 2, "default": 1}

    sup.stop()
    await asyncio.wait_for(task, timeout=2.0)


async def test_supervisor_scales_up_on_backlog(
    queue: MemoryQueue, container: Container
) -> None:
    import asyncio

    from pylar.queue import QueueConfig, QueuesConfig, QueueSupervisor

    # min=1, max=3, scale up at depth >= 2, fast cooldown for the test.
    cfg = QueuesConfig(queues={
        "default": QueueConfig(
            min_workers=1, max_workers=3,
            scale_threshold=2, scale_cooldown_seconds=0,
            tries=1, timeout=10,
        ),
    })
    sup = QueueSupervisor(queue, container, cfg, poll_seconds=0.05)

    # Pre-load enough records to clear the threshold without letting
    # workers drain them all instantly.
    from pylar.queue.record import JobRecord
    for i in range(20):
        await queue.push(JobRecord(
            id=f"j-{i}",
            job_class=f"{_SupervisorTestJob.__module__}.{_SupervisorTestJob.__qualname__}",
            payload_json=_SupervisorTestPayload(label="x").model_dump_json(),
            queue="default",
        ))

    task = asyncio.create_task(sup.run())
    # Give the supervisor a few ticks to react.
    await asyncio.sleep(0.5)
    sizes = sup.pool_sizes()
    assert sizes["default"] >= 2  # scaled past min_workers

    sup.stop()
    await asyncio.wait_for(task, timeout=2.0)


async def test_supervisor_scales_down_after_idle(
    queue: MemoryQueue, container: Container
) -> None:
    import asyncio

    from pylar.queue import QueueConfig, QueuesConfig, QueueSupervisor

    cfg = QueuesConfig(queues={
        "default": QueueConfig(
            min_workers=1, max_workers=3,
            scale_threshold=1, scale_cooldown_seconds=0,
        ),
    })
    sup = QueueSupervisor(queue, container, cfg, poll_seconds=0.02)

    task = asyncio.create_task(sup.run())
    await asyncio.sleep(0.1)
    # Force the pool above the floor so we can observe it shrinking.
    while len(sup._pools["default"].workers) < 3:
        sup._spawn_worker("default")
    assert len(sup._pools["default"].workers) == 3

    # Queue empty → after a couple of ticks past cooldown, supervisor drains
    # back down to min_workers=1.
    await asyncio.sleep(0.6)
    sizes = sup.pool_sizes()
    assert sizes["default"] == 1

    sup.stop()
    await asyncio.wait_for(task, timeout=2.0)
