"""End-to-end tests for the queue layer (dispatcher → memory queue → worker)."""

from __future__ import annotations

import pytest

from pylar.foundation import Container
from pylar.queue import (
    Dispatcher,
    Job,
    JobPayload,
    JobResolutionError,
    MemoryQueue,
    Worker,
)

# --------------------------------------------------------------------- domain


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []


class WelcomePayload(JobPayload):
    user_id: int
    email: str


class WelcomeJob(Job[WelcomePayload]):
    payload_type = WelcomePayload

    def __init__(self, recorder: _Recorder) -> None:
        self.recorder = recorder

    async def handle(self, payload: WelcomePayload) -> None:
        self.recorder.calls.append(("welcome", payload.email))


class FailingPayload(JobPayload):
    reason: str


class FailingJob(Job[FailingPayload]):
    payload_type = FailingPayload

    def __init__(self, recorder: _Recorder) -> None:
        self.recorder = recorder

    async def handle(self, payload: FailingPayload) -> None:
        self.recorder.calls.append(("fail", payload.reason))
        raise RuntimeError(payload.reason)


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


# ------------------------------------------------------------------------ tests


async def test_dispatch_pushes_serialised_record(
    dispatcher: Dispatcher, queue: MemoryQueue
) -> None:
    record = await dispatcher.dispatch(
        WelcomeJob, WelcomePayload(user_id=1, email="alice@example.com")
    )
    assert queue.qsize() == 1
    assert record.job_class.endswith("WelcomeJob")
    assert "alice@example.com" in record.payload_json


async def test_worker_runs_handle_with_typed_payload(
    dispatcher: Dispatcher,
    worker: Worker,
    container: Container,
) -> None:
    await dispatcher.dispatch(
        WelcomeJob, WelcomePayload(user_id=1, email="alice@example.com")
    )

    ran = await worker.process_next(timeout=0.1)
    assert ran is True
    assert container.make(_Recorder).calls == [("welcome", "alice@example.com")]


async def test_worker_acks_on_success(
    dispatcher: Dispatcher, worker: Worker, queue: MemoryQueue
) -> None:
    await dispatcher.dispatch(WelcomeJob, WelcomePayload(user_id=1, email="x@y"))
    await worker.process_next(timeout=0.1)
    assert len(queue.acked) == 1
    assert queue.failed == []


async def test_worker_marks_failed_when_handle_raises(
    dispatcher: Dispatcher,
    worker: Worker,
    queue: MemoryQueue,
    container: Container,
) -> None:
    await dispatcher.dispatch(FailingJob, FailingPayload(reason="boom"))
    await worker.process_next(timeout=0.1)

    assert queue.acked == []
    assert len(queue.failed) == 1
    _record, error = queue.failed[0]
    assert "boom" in error
    assert "RuntimeError" in error
    assert container.make(_Recorder).calls == [("fail", "boom")]


async def test_process_next_returns_false_on_empty_queue(worker: Worker) -> None:
    assert await worker.process_next(timeout=0.05) is False


async def test_worker_processes_jobs_in_dispatch_order(
    dispatcher: Dispatcher,
    worker: Worker,
    container: Container,
) -> None:
    await dispatcher.dispatch(WelcomeJob, WelcomePayload(user_id=1, email="a@a"))
    await dispatcher.dispatch(WelcomeJob, WelcomePayload(user_id=2, email="b@b"))
    await dispatcher.dispatch(WelcomeJob, WelcomePayload(user_id=3, email="c@c"))

    for _ in range(3):
        await worker.process_next(timeout=0.1)

    calls = container.make(_Recorder).calls
    assert [c[1] for c in calls] == ["a@a", "b@b", "c@c"]


# --------------------------------------------------------------- resolution


async def test_unknown_job_class_marks_record_failed(
    queue: MemoryQueue, worker: Worker
) -> None:
    from pylar.queue import JobRecord

    bad = JobRecord(
        id="bad-1",
        job_class="not.a.real.module.Job",
        payload_json="{}",
    )
    await queue.push(bad)
    await worker.process_next(timeout=0.1)

    assert len(queue.failed) == 1
    _, error = queue.failed[0]
    assert "JobResolutionError" in error or "Could not import" in error


async def test_resolve_job_class_unqualified_name_raises() -> None:
    with pytest.raises(JobResolutionError, match="fully qualified"):
        Worker._resolve_job_class("Bare")


async def test_run_loop_stops_when_stop_called(
    queue: MemoryQueue, worker: Worker
) -> None:
    import asyncio

    async def stop_soon() -> None:
        await asyncio.sleep(0.05)
        worker.stop()

    await asyncio.gather(worker.run(timeout=0.02), stop_soon())
    assert worker.is_stopping is True
