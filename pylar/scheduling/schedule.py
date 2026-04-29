"""The :class:`Schedule` — registry and runner of cron-style tasks."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import Any

from pylar.foundation.container import Container
from pylar.scheduling.builder import ScheduledTaskBuilder
from pylar.scheduling.task import (
    CallableTask,
    CommandTask,
    JobTask,
    ScheduledTask,
)


class Schedule:
    """The application's task schedule.

    Tasks are registered through the fluent ``command`` / ``call`` /
    ``job`` factories, each of which appends a new
    :class:`ScheduledTask` and returns a builder for further
    configuration. The schedule itself is a passive registry: an
    external cron entry calls ``pylar schedule:run`` once a minute,
    and the runner asks every task whether it is due.
    """

    def __init__(self) -> None:
        self._tasks: list[ScheduledTask] = []

    # ---------------------------------------------------------------- factories

    def command(self, name: str, args: Sequence[str] = ()) -> ScheduledTaskBuilder:
        """Schedule the console command identified by *name*."""
        task = CommandTask(command_name=name, args=args)
        self._tasks.append(task)
        return ScheduledTaskBuilder(task)

    def call(self, func: Callable[[], Awaitable[None]]) -> ScheduledTaskBuilder:
        """Schedule a no-argument async callable."""
        task = CallableTask(func)
        self._tasks.append(task)
        return ScheduledTaskBuilder(task)

    def job(self, job_cls: type[Any], payload: Any) -> ScheduledTaskBuilder:
        """Schedule the dispatch of a queue :class:`Job`.

        At the configured time the runner asks the container for the
        application's :class:`Dispatcher` and pushes a new record onto
        the queue with *payload*. A worker process picks the record up
        and executes the job — so a missed cron tick combined with the
        queue's retry policy still gets the work done.
        """
        task = JobTask(job_cls, payload)
        self._tasks.append(task)
        return ScheduledTaskBuilder(task)

    # ------------------------------------------------------------------- access

    def tasks(self) -> tuple[ScheduledTask, ...]:
        return tuple(self._tasks)

    def due(self, now: datetime) -> list[ScheduledTask]:
        return [task for task in self._tasks if task.is_due(now)]

    # ---------------------------------------------------------------- execution

    async def run_due(
        self,
        container: Container,
        *,
        now: datetime | None = None,
    ) -> int:
        """Run every task whose schedule matches *now*. Returns the count of tasks that ran.

        Tasks execute sequentially in registration order. A task that
        opted into ``without_overlapping`` first claims a cache lock;
        the runner silently skips tasks whose lock is already held by
        another runner (typically a previous tick that has not finished
        yet). Failures inside ``run`` propagate so operators see them
        in the cron output.
        """
        # The cache import is local because pylar.cache sits *above*
        # pylar.scheduling in the dependency graph by way of nothing —
        # the local import keeps that ordering optional, so users that
        # do not need overlap protection (and therefore do not register
        # a Cache binding) can still run scheduled tasks.
        from pylar.cache.cache import Cache

        moment = now if now is not None else datetime.now(UTC)
        due_now = self.due(moment)

        cache: Cache | None = None
        if container.has(Cache):
            cache = container.make(Cache)

        ran = 0
        for task in due_now:
            # Evaluate .when() / .skip() conditions before anything else.
            if not task.should_run():
                continue

            if task.lock_key is None:
                if await _run_with_hooks(task, container):
                    ran += 1
                continue

            if cache is None:
                raise RuntimeError(
                    f"Task {task.describe()} declared without_overlapping() but the "
                    f"container has no Cache binding. Register CacheServiceProvider "
                    f"or drop the overlap guard."
                )
            lock = cache.lock(task.lock_key, ttl=task.lock_ttl)
            acquired = await lock.acquire(blocking=False)
            if not acquired:
                # Another runner is still working on this task — skip
                # silently and let the next minute decide.
                continue
            try:
                if await _run_with_hooks(task, container):
                    ran += 1
            finally:
                await lock.release()

        return ran


async def _run_with_hooks(task: ScheduledTask, container: Container) -> bool:
    """Execute *task* with before/after/success/failure hooks.

    Returns ``True`` if the task completed without raising. Hooks that
    raise are logged but do not abort the main task flow. Failure
    hooks receive the exception, then the surrounding ``after`` hooks
    fire and the exception propagates to the caller so operators see
    it in the cron output.
    """
    import logging

    logger = logging.getLogger("pylar.scheduling")

    for hook in task.before_hooks:
        try:
            hook()
        except Exception:
            logger.exception("Scheduled task before hook raised")

    try:
        await task.run(container)
    except Exception as exc:
        # Mark-run even on failure so interval tasks don't hammer the
        # next tick retrying immediately — retry cadence is a
        # separate concern that belongs on the job/queue layer.
        task.mark_run(datetime.now(UTC))
        for failure_hook in task.failure_hooks:
            try:
                failure_hook(exc)
            except Exception:
                logger.exception("Scheduled task failure hook raised")
        for hook in task.after_hooks:
            try:
                hook()
            except Exception:
                logger.exception("Scheduled task after hook raised")
        raise
    else:
        task.mark_run(datetime.now(UTC))
        for hook in task.success_hooks:
            try:
                hook()
            except Exception:
                logger.exception("Scheduled task success hook raised")
        for hook in task.after_hooks:
            try:
                hook()
            except Exception:
                logger.exception("Scheduled task after hook raised")
        return True
