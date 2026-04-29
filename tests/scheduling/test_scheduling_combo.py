"""Tests for the scheduling features that pair with the cache layer.

Covers JobTask, without_overlapping (cache locks), and time-zone
aware schedules.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from pylar.cache import Cache, MemoryCacheStore
from pylar.foundation import Container
from pylar.queue import Dispatcher, Job, JobPayload, MemoryQueue
from pylar.scheduling import JobTask, Schedule

# --------------------------------------------------------------- domain


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[str] = []


class WelcomePayload(JobPayload):
    user_id: int


class WelcomeJob(Job[WelcomePayload]):
    payload_type = WelcomePayload

    async def handle(self, payload: WelcomePayload) -> None:
        return None  # the test inspects what was dispatched, not run


@pytest.fixture
def container() -> Container:
    container = Container()
    container.instance(_Recorder, _Recorder())
    queue = MemoryQueue()
    container.instance(MemoryQueue, queue)
    container.instance(Dispatcher, Dispatcher(queue))
    container.instance(Cache, Cache(MemoryCacheStore()))
    return container


# ----------------------------------------------------------- JobTask


async def test_job_task_dispatches_through_container(container: Container) -> None:
    schedule = Schedule()
    schedule.job(WelcomeJob, WelcomePayload(user_id=42)).every_minute()

    ran = await schedule.run_due(
        container, now=datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    )
    assert ran == 1

    queue = container.make(MemoryQueue)
    assert queue.qsize() == 1


async def test_job_task_describe() -> None:
    task = JobTask(WelcomeJob, WelcomePayload(user_id=1))
    assert "WelcomeJob" in task.describe()


# -------------------------------------------------------- without_overlapping


async def test_without_overlapping_skips_when_lock_held(
    container: Container,
) -> None:
    schedule = Schedule()
    recorder = container.make(_Recorder)

    async def slow() -> None:
        recorder.calls.append("slow")

    schedule.call(slow).every_minute().without_overlapping(ttl=10)

    # Pre-acquire the same lock under a name the builder will derive.
    cache = container.make(Cache)
    task = schedule.tasks()[0]
    assert task.lock_key is not None
    held = cache.lock(task.lock_key, ttl=10)
    await held.acquire()

    ran = await schedule.run_due(
        container, now=datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    )
    assert ran == 0
    assert recorder.calls == []  # the task was skipped

    await held.release()


async def test_without_overlapping_runs_when_lock_free(
    container: Container,
) -> None:
    schedule = Schedule()
    recorder = container.make(_Recorder)

    async def hit() -> None:
        recorder.calls.append("hit")

    schedule.call(hit).every_minute().without_overlapping(ttl=10)

    ran = await schedule.run_due(
        container, now=datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    )
    assert ran == 1
    assert recorder.calls == ["hit"]

    # The lock is released after the run, so the second invocation
    # also fires.
    ran_again = await schedule.run_due(
        container, now=datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    )
    assert ran_again == 1
    assert recorder.calls == ["hit", "hit"]


async def test_without_overlapping_uses_named_lock_key() -> None:
    schedule = Schedule()
    schedule.call(_noop).name("nightly").without_overlapping()
    task = schedule.tasks()[0]
    assert task.lock_key == "schedule:nightly"


async def test_without_overlapping_explicit_key() -> None:
    schedule = Schedule()
    schedule.call(_noop).every_minute().without_overlapping(key="custom-key", ttl=30)
    task = schedule.tasks()[0]
    assert task.lock_key == "custom-key"
    assert task.lock_ttl == 30


async def test_without_overlapping_without_cache_raises(container: Container) -> None:
    # Build a container that does not have Cache bound.
    bare = Container()
    schedule = Schedule()

    async def hit() -> None:
        return None

    schedule.call(hit).every_minute().without_overlapping()

    with pytest.raises(RuntimeError, match="without_overlapping"):
        await schedule.run_due(
            bare, now=datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        )


# --------------------------------------------------------------- timezone


def test_timezone_evaluates_in_local_zone() -> None:
    schedule = Schedule()
    # Daily at 02:00 in Europe/Riga (UTC+02:00 in winter, UTC+03:00 in summer).
    schedule.call(_noop).daily_at("02:00").timezone("Europe/Riga")
    task = schedule.tasks()[0]

    # Winter day — Riga is UTC+02:00. 02:00 local = 00:00 UTC.
    winter_now_utc = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)
    assert task.is_due(winter_now_utc) is True

    # 02:00 UTC the same day is 04:00 in Riga — not due.
    not_due = datetime(2026, 1, 5, 2, 0, tzinfo=UTC)
    assert task.is_due(not_due) is False


def test_timezone_summer_offset() -> None:
    schedule = Schedule()
    schedule.call(_noop).daily_at("02:00").timezone("Europe/Riga")
    task = schedule.tasks()[0]

    # Summer day — Riga is UTC+03:00 (DST). 02:00 local = 23:00 UTC the day before.
    summer_local_match = datetime(2026, 7, 9, 23, 0, tzinfo=UTC)
    assert task.is_due(summer_local_match) is True


def test_timezone_invalid_name_raises() -> None:
    from zoneinfo import ZoneInfoNotFoundError

    schedule = Schedule()
    builder = schedule.call(_noop).every_minute()
    with pytest.raises(ZoneInfoNotFoundError):
        builder.timezone("Not/A/Real/Zone")


def test_timezone_field_uses_zoneinfo() -> None:
    schedule = Schedule()
    schedule.call(_noop).every_minute().timezone("UTC")
    task = schedule.tasks()[0]
    assert isinstance(task.timezone, ZoneInfo)


# ------------------------------------------------------------------- noop


async def _noop() -> None:
    return None
