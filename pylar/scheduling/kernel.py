"""Long-running in-process scheduler — pylar's alternative to system cron.

The :class:`SchedulerKernel` is for deployments that prefer not to operate
a separate cron daemon: container-based environments where injecting a
sidecar is awkward, single-process applications, and dev workflows that
benefit from "everything is one process". The kernel sleeps until the
top of the next minute, asks :meth:`Schedule.run_due` to fire any task
whose cron expression matches, and repeats. Crash-safety is the
caller's responsibility — the same as system cron, but in the same
process.

For multi-instance deployments combine the kernel with
:meth:`pylar.scheduling.ScheduledTaskBuilder.on_one_server` so only one
node ever runs a given task; the cache lock then makes the kernel
cluster-aware without any extra coordination.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta

from pylar.foundation.container import Container
from pylar.scheduling.schedule import Schedule

_logger = logging.getLogger("pylar.scheduling")


class SchedulerKernel:
    """In-process scheduler that polls :class:`Schedule` once a minute.

    Usage::

        kernel = SchedulerKernel(container.make(Schedule), container)
        await kernel.run()  # blocks until stop() is called

    The kernel sleeps to the *top of the next minute* on every tick
    so cron expressions evaluate against full-minute boundaries the
    same way ``schedule:run`` would when invoked from a real cron
    job. A grace period (default: 5 seconds before the boundary)
    accounts for clock drift between the host and any shared lock
    backend.
    """

    def __init__(
        self,
        schedule: Schedule,
        container: Container,
        *,
        grace_seconds: float = 5.0,
    ) -> None:
        self._schedule = schedule
        self._container = container
        self._grace_seconds = grace_seconds
        self._stopping = False

    def stop(self) -> None:
        self._stopping = True

    @property
    def is_stopping(self) -> bool:
        return self._stopping

    async def run(self) -> None:
        """Loop until :meth:`stop` is called.

        Errors raised by individual tasks are logged and the loop
        continues — the kernel is the highest layer in the scheduling
        stack and there is nothing meaningful it can do beyond
        recording the failure. Catastrophic kernel failures (e.g. the
        Schedule itself becoming unusable) propagate.
        """
        self._stopping = False
        while not self._stopping:
            try:
                async with self._ambient_session_scope():
                    await self._schedule.run_due(self._container)
            except Exception:
                _logger.exception("Scheduler tick raised an exception")
            await self._sleep_until_next_tick()

    def _ambient_session_scope(self) -> AbstractAsyncContextManager[object]:
        """Open an ambient DB session around each tick if a manager is bound."""
        from contextlib import asynccontextmanager

        from pylar.database.connection import ConnectionManager
        from pylar.database.session import ambient_session

        if not self._container.has(ConnectionManager):
            @asynccontextmanager
            async def _noop() -> AsyncIterator[None]:
                yield

            return _noop()

        manager = self._container.make(ConnectionManager)
        return ambient_session(manager)

    async def _sleep_until_next_tick(self) -> None:
        """Sleep until the next tick boundary.

        When the schedule has no interval-based tasks the kernel
        paces itself to the top of the next minute, matching
        cron-style semantics. When at least one task declares
        ``interval_seconds``, the kernel instead sleeps up to the
        smallest configured interval so sub-minute cadences fire on
        schedule. In both cases we sleep in small slices so
        ``stop()`` is observed within a fraction of a second.
        """
        now = datetime.now(UTC)
        min_interval = self._minimum_interval_seconds()
        if min_interval is None:
            deadline = (now + timedelta(minutes=1)).replace(
                second=0, microsecond=0
            )
            grace = self._grace_seconds
        else:
            deadline = now + timedelta(seconds=max(1, min_interval))
            grace = 0.0

        while not self._stopping:
            now = datetime.now(UTC)
            remaining = (deadline - now).total_seconds() - grace
            if remaining <= 0:
                return
            await asyncio.sleep(min(0.25, remaining))

    def _minimum_interval_seconds(self) -> int | None:
        """Smallest ``interval_seconds`` across all scheduled tasks."""
        intervals = [
            t.interval_seconds
            for t in self._schedule.tasks()
            if t.interval_seconds is not None
        ]
        return min(intervals) if intervals else None
