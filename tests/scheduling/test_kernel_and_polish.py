"""Tests for SchedulerKernel, on_one_server, schedule:list next-run column."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from io import StringIO

import pytest

from pylar.foundation.container import Container
from pylar.scheduling import (
    Schedule,
    ScheduleListCommand,
    SchedulerKernel,
)

# ----------------------------------------------------------- next_run_at


def test_next_run_at_returns_future_datetime() -> None:
    schedule = Schedule()
    schedule.call(_noop).cron("*/5 * * * *")
    task = schedule.tasks()[0]
    base = datetime(2026, 4, 9, 10, 7, tzinfo=UTC)
    nxt = task.next_run_at(base)
    assert nxt > base
    assert nxt.minute % 5 == 0


async def _noop() -> None:
    return None


# ----------------------------------------------------------- schedule:list


async def test_schedule_list_includes_next_run_column() -> None:
    from pylar.console.output import Output

    schedule = Schedule()
    schedule.call(_noop).every_minute().name("ping")
    schedule.call(_noop).hourly().name("hourly-job")

    buf = StringIO()
    cmd = ScheduleListCommand(schedule, Output(buf, colour=False))
    await cmd.handle(cmd.input_type())
    output = buf.getvalue()
    assert "ping" in output
    assert "hourly-job" in output
    assert "from now" in output  # human-readable relative time
    assert "20" in output  # current decade (year in Next Due column)


# ----------------------------------------------------------- on_one_server


def test_on_one_server_sets_overlap_lock_with_long_ttl() -> None:
    schedule = Schedule()
    schedule.call(_noop).every_minute().name("singleton").on_one_server()
    task = schedule.tasks()[0]
    assert task.lock_key is not None
    assert task.lock_ttl == 3600


def test_on_one_server_with_custom_ttl() -> None:
    schedule = Schedule()
    schedule.call(_noop).every_minute().name("nightly").on_one_server(ttl=7200)
    assert schedule.tasks()[0].lock_ttl == 7200


# ----------------------------------------------------------- SchedulerKernel


_calls: list[datetime] = []


async def _record() -> None:
    _calls.append(datetime.now(UTC))


@pytest.fixture(autouse=True)
def _clear_calls() -> None:
    _calls.clear()


async def test_kernel_runs_due_tasks_through_schedule() -> None:
    schedule = Schedule()
    schedule.call(_record).every_minute()
    container = Container()
    SchedulerKernel(schedule, container)

    # Drive one tick manually rather than waiting a full minute.
    await schedule.run_due(container)
    assert len(_calls) == 1


async def test_kernel_stop_breaks_loop() -> None:
    schedule = Schedule()
    schedule.call(_record).every_minute()
    container = Container()
    kernel = SchedulerKernel(schedule, container, grace_seconds=0.0)

    async def runner() -> None:
        await kernel.run()

    task = asyncio.create_task(runner())
    await asyncio.sleep(0.05)  # let it enter the first sleep
    kernel.stop()
    # Wait at most one tick + a margin for the loop to notice.
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except TimeoutError:
        task.cancel()
        raise
