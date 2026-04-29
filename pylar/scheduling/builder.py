"""Fluent builder that decorates a :class:`ScheduledTask` with frequency hints."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Self

from pylar.scheduling.task import ScheduledTask


class ScheduledTaskBuilder:
    """Chainable wrapper around a freshly registered :class:`ScheduledTask`.

    Returned by ``Schedule.command`` / ``Schedule.call``. Every fluent
    method mutates the underlying task in place and returns ``self``,
    so users can compose ``daily_at`` / ``name`` / ``cron`` in any order.
    """

    def __init__(self, task: ScheduledTask) -> None:
        self._task = task

    @property
    def task(self) -> ScheduledTask:
        return self._task

    # ----------------------------------------------------------------- frequency

    def cron(self, expression: str) -> Self:
        """Set an arbitrary cron expression. The most expressive option."""
        self._task.set_cron(expression)
        return self

    def every_seconds(self, seconds: int) -> Self:
        """Fire every *seconds* — use for sub-minute cadences.

        Cron expressions cap at one-minute resolution. For tight
        polling work the scheduler supports interval-based tasks:
        ``schedule.command("...").every_seconds(10)`` fires every
        ten seconds whenever the in-process scheduler kernel is
        running with a tick frequency at least as fast as the
        interval (it adapts automatically — see
        :class:`SchedulerKernel`).

        Not supported by system-cron-driven ``pylar schedule:run``
        invocations: those still tick once a minute, so the most a
        command can fire via the external cron path is once per
        minute even if the interval is shorter.
        """
        self._task.set_interval(seconds)
        return self

    def every_five_seconds(self) -> Self:
        return self.every_seconds(5)

    def every_ten_seconds(self) -> Self:
        return self.every_seconds(10)

    def every_thirty_seconds(self) -> Self:
        return self.every_seconds(30)

    def every_minute(self) -> Self:
        return self.cron("* * * * *")

    def every_five_minutes(self) -> Self:
        return self.cron("*/5 * * * *")

    def every_ten_minutes(self) -> Self:
        return self.cron("*/10 * * * *")

    def hourly(self) -> Self:
        return self.cron("0 * * * *")

    def hourly_at(self, minute: int) -> Self:
        return self.cron(f"{minute} * * * *")

    def daily(self) -> Self:
        return self.cron("0 0 * * *")

    def daily_at(self, time: str) -> Self:
        """Run once per day at ``HH:MM`` (24-hour clock)."""
        hour_str, minute_str = time.split(":", 1)
        return self.cron(f"{int(minute_str)} {int(hour_str)} * * *")

    def weekly(self) -> Self:
        return self.cron("0 0 * * 0")

    def weekly_on(self, day_of_week: int, time: str) -> Self:
        hour_str, minute_str = time.split(":", 1)
        return self.cron(f"{int(minute_str)} {int(hour_str)} * * {day_of_week}")

    def monthly(self) -> Self:
        return self.cron("0 0 1 * *")

    # ------------------------------------------------------------------ timezone

    def timezone(self, name: str) -> Self:
        """Evaluate the cron expression in the named time zone.

        ``name`` is forwarded to :class:`zoneinfo.ZoneInfo`. A
        ``"02:00"`` daily task in ``Europe/Riga`` then runs at 02:00
        local time, not at 02:00 UTC.
        """
        self._task.set_timezone(name)
        return self

    # ----------------------------------------------------------- overlap guard

    def without_overlapping(
        self,
        *,
        ttl: int = 60,
        key: str | None = None,
    ) -> Self:
        """Refuse to start a second copy while the first is still running.

        The :class:`Schedule` runner uses the bound :class:`Cache` (if
        any) to claim a lock on *key* before invoking the task; the
        run is silently skipped when the lock is already held. ``ttl``
        is the maximum time pylar holds the lock — a long-running task
        that exceeds it will see a second instance start, so size the
        TTL generously above the realistic worst case.

        ``key`` defaults to a stable name derived from the task name
        (or class) so two scheduled instances of the same job never
        race even if both omit the argument.
        """
        self._task.lock_key = key or self._default_lock_key()
        self._task.lock_ttl = ttl
        return self

    def on_one_server(self, *, ttl: int = 3600) -> Self:
        """Run the task on at most one cluster node at a time.

        Sugar over :meth:`without_overlapping` with a longer default
        TTL — the intent is "this task is *cluster-wide* singleton",
        not "skip a tick if the previous one is still running". The
        bound :class:`Cache` must point at a shared backend (database,
        Redis) for the cluster guarantee to hold; with the in-memory
        store the lock is process-local.
        """
        return self.without_overlapping(ttl=ttl)

    def _default_lock_key(self) -> str:
        if self._task.name:
            return f"schedule:{self._task.name}"
        return f"schedule:{type(self._task).__name__}:{id(self._task):x}"

    # -------------------------------------------------------------------- naming

    def name(self, name: str) -> Self:
        """Attach a human-readable name shown by ``pylar schedule:list``."""
        self._task.name = name
        return self

    # --------------------------------------------------------------- output

    def send_output_to(self, path: str) -> Self:
        """Write task stdout/stderr to *path* in storage after execution.

        *path* is relative to the bound storage root::

            schedule.command("reports:generate").daily().send_output_to(
                "logs/reports.log"
            )
        """
        self._task.output_path = path
        return self

    def email_output_to(self, address: str) -> Self:
        """Email task output on failure.

        The notification is sent via the bound :class:`Mailer` when
        the task raises an exception::

            schedule.command("billing:charge").daily().email_output_to(
                "ops@example.com"
            )
        """
        self._task.email_on_failure = address
        return self

    # -------------------------------------------------------------- hooks

    def before(self, callback: Callable[[], Any]) -> Self:
        """Run *callback* before the task executes.

        Multiple ``before`` hooks fire in registration order. Return
        value is ignored. Use :meth:`skip` / :meth:`when` for
        conditional execution instead::

            schedule.command("reports:run").daily().before(lambda: log("start"))
        """
        self._task.before_hooks.append(callback)
        return self

    def after(self, callback: Callable[[], Any]) -> Self:
        """Run *callback* after the task finishes (success or failure)."""
        self._task.after_hooks.append(callback)
        return self

    def on_success(self, callback: Callable[[], Any]) -> Self:
        """Run *callback* only when the task completes without raising."""
        self._task.success_hooks.append(callback)
        return self

    def on_failure(self, callback: Callable[[Exception], Any]) -> Self:
        """Run *callback(exc)* when the task raises."""
        self._task.failure_hooks.append(callback)
        return self

    # ---------------------------------------------------------- conditions

    def when(self, condition: Callable[[], bool | Any]) -> Self:
        """Run the task only when *condition()* returns truthy.

        Multiple ``when`` conditions are AND-combined — the task runs
        only if every condition passes::

            schedule.command("newsletter:send").hourly().when(
                lambda: is_business_hours()
            )
        """
        self._task.when_conditions.append(condition)
        return self

    def skip(self, condition: Callable[[], bool | Any]) -> Self:
        """Skip the task when *condition()* returns truthy.

        Opposite of :meth:`when` — useful for opting out while the
        default is "run"::

            schedule.command("backup:run").daily().skip(lambda: is_weekend())
        """
        self._task.skip_conditions.append(condition)
        return self
