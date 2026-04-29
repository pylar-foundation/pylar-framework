"""Behavioural tests for the scheduling layer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from pylar.console.command import Command
from pylar.console.kernel import COMMANDS_TAG
from pylar.foundation import Container
from pylar.scheduling import (
    CallableTask,
    CommandTask,
    InvalidCronExpressionError,
    Schedule,
)

# --------------------------------------------------------------------- helpers


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[str] = []


@dataclass(frozen=True)
class _NoArgs:
    pass


class _BackupCommand(Command[_NoArgs]):
    name = "backup:run"
    description = "test command"
    input_type = _NoArgs

    def __init__(self, recorder: _Recorder) -> None:
        self.recorder = recorder

    async def handle(self, input: _NoArgs) -> int:
        self.recorder.calls.append("backup")
        return 0


@pytest.fixture
def container() -> Container:
    container = Container()
    container.instance(_Recorder, _Recorder())
    container.tag([_BackupCommand], COMMANDS_TAG)
    return container


# ----------------------------------------------------------------- builder API


def test_every_minute_sets_star_cron() -> None:
    schedule = Schedule()
    schedule.call(_noop).every_minute()
    assert schedule.tasks()[0].cron_expression == "* * * * *"


def test_daily_at_translates_to_cron() -> None:
    schedule = Schedule()
    schedule.call(_noop).daily_at("02:30")
    assert schedule.tasks()[0].cron_expression == "30 2 * * *"


def test_hourly_at() -> None:
    schedule = Schedule()
    schedule.call(_noop).hourly_at(15)
    assert schedule.tasks()[0].cron_expression == "15 * * * *"


def test_weekly_on_sunday_morning() -> None:
    schedule = Schedule()
    schedule.call(_noop).weekly_on(0, "06:00")
    assert schedule.tasks()[0].cron_expression == "0 6 * * 0"


def test_invalid_cron_rejected() -> None:
    schedule = Schedule()
    with pytest.raises(InvalidCronExpressionError):
        schedule.call(_noop).cron("definitely not cron")


def test_name_is_assigned() -> None:
    schedule = Schedule()
    schedule.call(_noop).daily().name("nightly cleanup")
    assert schedule.tasks()[0].name == "nightly cleanup"


# ------------------------------------------------------------------- is_due


def test_is_due_matches_exact_minute() -> None:
    task = CallableTask(_noop)
    task.set_cron("30 2 * * *")
    assert task.is_due(datetime(2026, 1, 1, 2, 30, tzinfo=UTC)) is True


def test_is_due_rejects_other_minutes() -> None:
    task = CallableTask(_noop)
    task.set_cron("30 2 * * *")
    assert task.is_due(datetime(2026, 1, 1, 2, 31, tzinfo=UTC)) is False
    assert task.is_due(datetime(2026, 1, 1, 3, 30, tzinfo=UTC)) is False


def test_every_minute_always_due() -> None:
    task = CallableTask(_noop)
    task.set_cron("* * * * *")
    for hour in (0, 6, 12, 23):
        assert task.is_due(datetime(2026, 1, 1, hour, 0, tzinfo=UTC))


# --------------------------------------------------------------- run_due


async def test_run_due_executes_only_due_callable_tasks(container: Container) -> None:
    recorder = container.make(_Recorder)
    schedule = Schedule()

    async def hit() -> None:
        recorder.calls.append("call")

    schedule.call(hit).daily_at("02:30")
    schedule.call(hit).daily_at("18:00")  # not due

    ran = await schedule.run_due(
        container, now=datetime(2026, 1, 1, 2, 30, tzinfo=UTC)
    )
    assert ran == 1
    assert recorder.calls == ["call"]


async def test_run_due_dispatches_command_tasks(container: Container) -> None:
    recorder = container.make(_Recorder)
    schedule = Schedule()
    schedule.command("backup:run").daily_at("02:00")

    ran = await schedule.run_due(
        container, now=datetime(2026, 1, 1, 2, 0, tzinfo=UTC)
    )
    assert ran == 1
    assert recorder.calls == ["backup"]


async def test_run_due_with_no_matches_returns_zero(container: Container) -> None:
    schedule = Schedule()
    schedule.call(_noop).daily_at("02:00")
    ran = await schedule.run_due(
        container, now=datetime(2026, 1, 1, 5, 0, tzinfo=UTC)
    )
    assert ran == 0


def test_command_task_describe() -> None:
    task = CommandTask("backup:run", args=("--force",))
    task.set_cron("0 2 * * *")
    assert task.describe() == "command backup:run --force"


def test_callable_task_describe() -> None:
    task = CallableTask(_noop)
    assert "_noop" in task.describe()


# ------------------------------------------------------------------ noop


async def _noop() -> None:
    return None


# ---------------------------- Sub-minute interval scheduling


async def test_interval_task_is_due_on_first_tick_then_after_elapsed() -> None:
    """An interval task fires once, then waits for ``interval_seconds``."""
    from datetime import UTC, datetime, timedelta

    from pylar.scheduling.task import CallableTask

    async def _noop() -> None:
        return None

    task = CallableTask(_noop)
    task.set_interval(10)

    start = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    # Never run → due.
    assert task.is_due(start) is True
    task.mark_run(start)
    # Immediately after a tick → not due.
    assert task.is_due(start + timedelta(seconds=1)) is False
    assert task.is_due(start + timedelta(seconds=9)) is False
    # Exactly at the interval boundary and past it → due.
    assert task.is_due(start + timedelta(seconds=10)) is True
    assert task.is_due(start + timedelta(seconds=15)) is True


async def test_every_ten_seconds_builder_sets_interval() -> None:
    from pylar.scheduling.schedule import Schedule

    schedule = Schedule()
    (
        schedule.command("heartbeat")
        .every_ten_seconds()
        .name("every-ten")
    )
    (task,) = schedule.tasks()
    assert task.interval_seconds == 10
    assert task.name == "every-ten"


async def test_set_interval_rejects_zero_or_negative() -> None:
    import pytest

    from pylar.scheduling.task import CallableTask

    async def _noop() -> None:
        return None

    task = CallableTask(_noop)
    with pytest.raises(ValueError, match="positive"):
        task.set_interval(0)
    with pytest.raises(ValueError, match="positive"):
        task.set_interval(-5)


async def test_interval_supersedes_previous_cron() -> None:
    """``set_interval`` clears any in-flight cron expression state."""
    from pylar.scheduling.task import CallableTask

    async def _noop() -> None:
        return None

    task = CallableTask(_noop)
    task.set_cron("0 3 * * *")
    task.set_interval(30)
    assert task.interval_seconds == 30


async def test_cron_supersedes_previous_interval() -> None:
    """Switching from interval back to cron wipes ``interval_seconds``."""
    from pylar.scheduling.task import CallableTask

    async def _noop() -> None:
        return None

    task = CallableTask(_noop)
    task.set_interval(30)
    task.set_cron("0 3 * * *")
    assert task.interval_seconds is None
