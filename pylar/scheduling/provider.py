"""Service provider that wires the scheduling layer."""

from __future__ import annotations

from pylar.console.kernel import COMMANDS_TAG
from pylar.foundation.container import Container
from pylar.foundation.provider import ServiceProvider
from pylar.scheduling.commands import (
    ScheduleListCommand,
    ScheduleRunCommand,
    ScheduleTestCommand,
    ScheduleWorkCommand,
)
from pylar.scheduling.schedule import Schedule


class SchedulingServiceProvider(ServiceProvider):
    """Bind the application :class:`Schedule` and tag the schedule commands.

    User projects subclass this provider and override
    :meth:`register_schedule` to declare their tasks in one place::

        class AppSchedulingServiceProvider(SchedulingServiceProvider):
            def register_schedule(self, schedule: Schedule) -> None:
                schedule.command("backup:run").daily_at("02:00").name("nightly backup")
                schedule.call(cleanup_temp_files).hourly()
    """

    def register(self, container: Container) -> None:
        schedule = Schedule()
        self.register_schedule(schedule)
        container.singleton(Schedule, lambda: schedule)
        container.tag(
            [
                ScheduleRunCommand,
                ScheduleListCommand,
                ScheduleWorkCommand,
                ScheduleTestCommand,
            ],
            COMMANDS_TAG,
        )

    def register_schedule(self, schedule: Schedule) -> None:
        """Override in user code to declare scheduled tasks.

        The default implementation is a no-op so applications with no
        scheduled work can list this provider in ``config/app.py``
        without subclassing.
        """
