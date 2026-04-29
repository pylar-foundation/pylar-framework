"""Console commands for the scheduling layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from pylar.console.command import Command
from pylar.console.output import Output
from pylar.foundation.container import Container
from pylar.scheduling.kernel import SchedulerKernel
from pylar.scheduling.schedule import Schedule


def _humanize_delta(delta: timedelta) -> str:
    """Render a future timedelta like Laravel: ``23 hours from now``."""
    seconds = int(delta.total_seconds())
    if seconds < 0:
        return "overdue"
    if seconds < 60:
        return "less than a minute from now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''} from now"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''} from now"
    days = hours // 24
    if days < 30:
        return f"{days} day{'s' if days != 1 else ''} from now"
    months = days // 30
    if months < 12:
        return f"{months} month{'s' if months != 1 else ''} from now"
    years = days // 365
    return f"{years} year{'s' if years != 1 else ''} from now"


@dataclass(frozen=True)
class _ScheduleRunInput:
    """No arguments — runs whichever tasks are due right now."""


class ScheduleRunCommand(Command[_ScheduleRunInput]):
    name = "schedule:run"
    description = "Run scheduled tasks that are due at the current minute"
    input_type = _ScheduleRunInput

    def __init__(self, schedule: Schedule, container: Container, output: Output) -> None:
        self.schedule = schedule
        self.container = container
        self.out = output

    async def handle(self, input: _ScheduleRunInput) -> int:
        ran = await self.schedule.run_due(self.container)
        self.out.info(f"Ran {ran} scheduled task(s).")
        return 0


@dataclass(frozen=True)
class _ScheduleListInput:
    """No arguments — prints every registered scheduled task."""


class ScheduleListCommand(Command[_ScheduleListInput]):
    name = "schedule:list"
    description = "List every scheduled task and its cron expression"
    input_type = _ScheduleListInput

    def __init__(self, schedule: Schedule, output: Output) -> None:
        self.schedule = schedule
        self.out = output

    async def handle(self, input: _ScheduleListInput) -> int:
        tasks = self.schedule.tasks()
        if not tasks:
            self.out.info("No scheduled tasks.")
            return 0
        now = datetime.now(UTC)
        rows: list[tuple[str, ...]] = []
        for task in tasks:
            next_at = task.next_run_at(now)
            label = task.name or task.describe()
            rows.append((
                task.cron_expression,
                label,
                next_at.strftime("%Y-%m-%d %H:%M %Z"),
                _humanize_delta(next_at - now),
            ))
        self.out.table(
            headers=("Cron", "Task", "Next Due", "When"),
            rows=rows,
            title="Scheduled Tasks",
        )
        return 0


# ----------------------------------------------------------- schedule:work


@dataclass(frozen=True)
class _ScheduleWorkInput:
    """No arguments — runs the SchedulerKernel until interrupted."""


class ScheduleWorkCommand(Command[_ScheduleWorkInput]):
    """Long-running scheduler — polls and runs tasks every minute in-process.

    Mirrors Laravel's ``php artisan schedule:work``. Useful in container
    deployments where injecting a sidecar cron is awkward. Use ``Ctrl-C``
    or send SIGTERM to stop gracefully.
    """

    name = "schedule:work"
    description = "Run the scheduler as a long-running process (alternative to cron)"
    input_type = _ScheduleWorkInput

    def __init__(self, schedule: Schedule, container: Container, output: Output) -> None:
        self.schedule = schedule
        self.container = container
        self.out = output

    async def handle(self, input: _ScheduleWorkInput) -> int:
        import asyncio
        import signal

        kernel = SchedulerKernel(self.schedule, self.container)

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, kernel.stop)
            except NotImplementedError:
                pass  # Windows

        self.out.info("Scheduler running. Press Ctrl-C to stop.")
        try:
            await kernel.run()
        except KeyboardInterrupt:
            kernel.stop()
        self.out.newline()
        self.out.info("Scheduler stopped.")
        return 0


# ----------------------------------------------------------- schedule:test


@dataclass(frozen=True)
class _ScheduleTestInput:
    name: str = field(
        default="",
        metadata={"help": "Name of the scheduled task to run immediately"},
    )


class ScheduleTestCommand(Command[_ScheduleTestInput]):
    """Run a single scheduled task immediately — useful for debugging.

    Matches ``php artisan schedule:test`` in Laravel. Without ``--name``
    lists every available task name and exits. With ``--name`` locates
    the task by its ``.name()`` label and executes it once, bypassing
    the cron check but still honouring hooks and conditions.
    """

    name = "schedule:test"
    description = "Execute a scheduled task by name (bypasses cron check)"
    input_type = _ScheduleTestInput

    def __init__(self, schedule: Schedule, container: Container, output: Output) -> None:
        self.schedule = schedule
        self.container = container
        self.out = output

    async def handle(self, input: _ScheduleTestInput) -> int:
        tasks = self.schedule.tasks()
        if not input.name:
            self.out.line("Usage: pylar schedule:test --name <task-name>")
            self.out.newline()
            self.out.line("Available tasks:")
            for task in tasks:
                label = task.name or task.describe()
                self.out.line(f"  {label}")
            return 1

        target = next(
            (t for t in tasks if (t.name or t.describe()) == input.name),
            None,
        )
        if target is None:
            self.out.error(f"No scheduled task named {input.name!r}.")
            return 1

        from pylar.scheduling.schedule import _run_with_hooks

        self.out.action("Running", input.name)
        try:
            await _run_with_hooks(target, self.container)
        except Exception as exc:
            self.out.error(f"Task failed: {exc}")
            return 1
        self.out.success("Done.")
        return 0
