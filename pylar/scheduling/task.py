"""Scheduled task hierarchy and the cron-matching logic."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime, timedelta, tzinfo
from typing import Any
from zoneinfo import ZoneInfo

from croniter import croniter

from pylar.foundation.container import Container
from pylar.scheduling.exceptions import InvalidCronExpressionError


class ScheduledTask(ABC):
    """Base class for everything the :class:`Schedule` knows how to run.

    A scheduled task carries:

    * a cron expression deciding *when* it fires,
    * an optional human-readable name,
    * optional overlap protection settings (lock key + TTL) so the
      :class:`Schedule` can serialise concurrent invocations through
      a cache lock,
    * an optional time zone for the cron evaluation,
    * an :meth:`run` hook that defines *what* it does.
    """

    def __init__(self) -> None:
        self.cron_expression: str = "* * * * *"
        #: Sub-minute interval in seconds, or ``None`` to use
        #: :attr:`cron_expression`. When set, the scheduler fires the
        #: task every ``interval_seconds`` seconds regardless of what
        #: the cron expression says — useful for tight polling work
        #: that cron cannot express (minimum cron granularity is one
        #: minute). The bookkeeping lives on the task instance
        #: (``_last_run_at``) so the scheduler can decide whether
        #: enough time has elapsed since the last successful tick.
        self.interval_seconds: int | None = None
        self._last_run_at: datetime | None = None
        self.name: str | None = None
        self.lock_key: str | None = None
        self.lock_ttl: int = 60
        self.timezone: tzinfo | None = None
        self.output_path: str | None = None
        self.email_on_failure: str | None = None
        # Lifecycle hooks — callables invoked by the runner around run().
        # Each list preserves registration order; all hooks in a category
        # fire, even if some raise.
        self.before_hooks: list[Callable[[], Any]] = []
        self.after_hooks: list[Callable[[], Any]] = []
        self.success_hooks: list[Callable[[], Any]] = []
        self.failure_hooks: list[Callable[[Exception], Any]] = []
        # Conditions — run() is skipped unless *all* `when` callables
        # return truthy AND *all* `skip` callables return falsy.
        self.when_conditions: list[Callable[[], bool | Any]] = []
        self.skip_conditions: list[Callable[[], bool | Any]] = []

    def should_run(self) -> bool:
        """Evaluate ``.when()`` / ``.skip()`` conditions.

        Returns ``True`` if the task should execute at this tick,
        ``False`` if any condition vetoes it. Missing ``.when()`` /
        ``.skip()`` means "no veto".
        """
        for cond in self.when_conditions:
            if not cond():
                return False
        for cond in self.skip_conditions:
            if cond():
                return False
        return True

    def set_cron(self, expression: str) -> None:
        if not croniter.is_valid(expression):
            raise InvalidCronExpressionError(f"Invalid cron expression: {expression!r}")
        self.cron_expression = expression
        self.interval_seconds = None  # cron and interval are mutually exclusive

    def set_interval(self, seconds: int) -> None:
        """Fire the task every *seconds* instead of on a cron boundary.

        Supersedes any cron expression set on the task. The scheduler
        kernel must be running with a tick frequency at least as fast
        as this interval; the builder's :meth:`every_seconds` helper
        is the supported surface for end users.
        """
        if seconds <= 0:
            raise ValueError(
                f"Interval must be positive, got {seconds!r}",
            )
        self.interval_seconds = seconds

    def set_timezone(self, name: str) -> None:
        """Evaluate the cron expression in the named time zone.

        ``name`` is forwarded to :class:`zoneinfo.ZoneInfo`. The lookup
        happens at decoration time so a typo in the time-zone name
        fails fast at provider boot rather than during the first
        ``schedule:run``.
        """
        self.timezone = ZoneInfo(name)

    def is_due(self, now: datetime) -> bool:
        """Return True when *now* is a fire time for this task.

        When :attr:`interval_seconds` is set, the task is due as soon
        as ``now - _last_run_at`` reaches the configured interval (or
        on the very first tick, before the task has ever run). The
        cron path is used otherwise: ``now`` is converted into the
        task's time zone (if any) and compared against the previous
        cron boundary — minute precision.
        """
        if self.interval_seconds is not None:
            if self._last_run_at is None:
                return True
            elapsed = (now - self._last_run_at).total_seconds()
            return elapsed >= self.interval_seconds

        moment = now
        if self.timezone is not None:
            moment = moment.astimezone(self.timezone)

        iterator = croniter(self.cron_expression, moment + timedelta(seconds=1))
        previous: datetime = iterator.get_prev(datetime)
        return bool(
            previous.year == moment.year
            and previous.month == moment.month
            and previous.day == moment.day
            and previous.hour == moment.hour
            and previous.minute == moment.minute
        )

    def mark_run(self, at: datetime) -> None:
        """Record that the task just ran at *at*.

        The scheduler invokes this after a successful (or caught)
        tick so :meth:`is_due` can compare against the previous run
        for interval-based tasks. A no-op for cron-only tasks, kept
        on the base class so every task shape carries the same
        bookkeeping surface.
        """
        self._last_run_at = at

    def next_run_at(self, now: datetime) -> datetime:
        """Return the next datetime at which this task is due *after* ``now``.

        For interval tasks the answer is:

        * ``_last_run_at + interval`` when the task has already run —
          the exact point at which the next tick will fire.
        * ``now + interval`` when the task has never run in *this*
          process. The admin HTTP process and the scheduler process
          generally do not share ``_last_run_at`` bookkeeping (it
          lives in-process on the ``ScheduledTask`` instance), so a
          dashboard served from ``uvicorn`` would otherwise always
          see ``now`` and report "due now" as a permanent state.
          Treating a missing ``_last_run_at`` as "one full interval
          away" gives the UI a predictable countdown; the actual
          fire time is owned by whichever process runs
          ``schedule:work``.

        For cron tasks it's the next cron boundary past *now* in the
        task's time zone.
        """
        if self.interval_seconds is not None:
            anchor = self._last_run_at if self._last_run_at is not None else now
            return anchor + timedelta(seconds=self.interval_seconds)

        moment = now
        if self.timezone is not None:
            moment = moment.astimezone(self.timezone)
        iterator = croniter(self.cron_expression, moment)
        next_dt: datetime = iterator.get_next(datetime)
        return next_dt

    @abstractmethod
    async def run(self, container: Container) -> None:
        """Execute the task. Errors propagate to the schedule runner."""

    @abstractmethod
    def describe(self) -> str:
        """Return a one-line human description used by ``schedule:list``."""


class CallableTask(ScheduledTask):
    """A scheduled async function. The function is called with no arguments."""

    def __init__(self, func: Callable[[], Awaitable[None]]) -> None:
        super().__init__()
        self._func = func

    async def run(self, container: Container) -> None:
        await self._func()

    def describe(self) -> str:
        qualified = getattr(self._func, "__qualname__", repr(self._func))
        return f"call {qualified}"


class CommandTask(ScheduledTask):
    """A scheduled console command. Resolved through the container's command tag."""

    def __init__(self, command_name: str, args: Sequence[str] = ()) -> None:
        super().__init__()
        self._command_name = command_name
        self._args = list(args)

    @property
    def command_name(self) -> str:
        return self._command_name

    async def run(self, container: Container) -> None:
        # Local imports avoid a hard dependency from the scheduler module
        # onto the console layer at module load time.
        from pylar.console.command import Command
        from pylar.console.kernel import COMMANDS_TAG

        index: dict[str, type[Command[object]]] = {}
        for cls in container.tagged_types(COMMANDS_TAG):
            if not issubclass(cls, Command):
                continue
            index[cls.name] = cls
        if self._command_name not in index:
            raise RuntimeError(
                f"Scheduled command {self._command_name!r} is not registered "
                f"in {COMMANDS_TAG}"
            )
        command_cls = index[self._command_name]
        parsed = command_cls.parse(self._args)
        instance = container.make(command_cls)
        await instance.handle(parsed)

    def describe(self) -> str:
        rendered_args = " ".join(self._args)
        suffix = f" {rendered_args}" if rendered_args else ""
        return f"command {self._command_name}{suffix}"


class JobTask(ScheduledTask):
    """A scheduled :class:`pylar.queue.Job` dispatched onto the bound queue.

    The task does not run the job synchronously — it asks the
    container for the application's :class:`Dispatcher` and pushes a
    new record onto the queue with the configured payload. A worker
    process then handles the actual execution.

    This is the recommended path for any scheduled work that should
    survive a missed cron tick: the queue's retry policy and failed
    pool kick in for free.
    """

    def __init__(self, job_cls: type[Any], payload: Any) -> None:
        super().__init__()
        self._job_cls = job_cls
        self._payload = payload

    @property
    def job_class(self) -> type[Any]:
        return self._job_cls

    async def run(self, container: Container) -> None:
        # Local import — scheduling is layered above the queue module,
        # but the import would still create a load-time cycle if the
        # queue layer ever grew a dependency on scheduling.
        from pylar.queue import Dispatcher

        dispatcher = container.make(Dispatcher)
        await dispatcher.dispatch(self._job_cls, self._payload)

    def describe(self) -> str:
        return f"job {self._job_cls.__qualname__}"
