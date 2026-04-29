"""Console commands for the observability surface.

* :class:`AboutCommand` prints a Laravel-style summary of the resolved
  application config — providers, database driver, cache/queue/storage
  bindings, scheduled tasks.
* :class:`DoctorCommand` lives in :mod:`pylar.observability.doctor`
  next door; both are tagged from
  :class:`pylar.observability.ObservabilityServiceProvider`.
"""

from __future__ import annotations

from dataclasses import dataclass

from pylar.console.command import Command
from pylar.console.kernel import COMMANDS_TAG
from pylar.console.output import Output
from pylar.foundation.application import Application
from pylar.foundation.container import Container


@dataclass(frozen=True)
class _AboutInput:
    """No arguments — dumps the full about table."""


class AboutCommand(Command[_AboutInput]):
    """``pylar about`` — print resolved config, providers, and drivers.

    Laravel's ``php artisan about`` inspired the output format. The
    command reads everything it needs out of the container so the
    output stays accurate even when providers rewire bindings in their
    ``boot`` phase.
    """

    name = "about"
    description = "Print application config, registered providers, and drivers"
    input_type = _AboutInput

    def __init__(
        self,
        app: Application,
        container: Container,
        output: Output,
    ) -> None:
        self.app = app
        self.container = container
        self.out = output

    async def handle(self, input: _AboutInput) -> int:
        self.out.newline()
        self._print_application_section()
        self._print_database_section()
        self._print_cache_section()
        self._print_queue_section()
        self._print_providers_section()
        self._print_routes_section()
        self._print_schedule_section()
        return 0

    # ------------------------------------------------------------- sections

    def _print_application_section(self) -> None:
        rows: list[tuple[str, str]] = [
            ("Name", self.app.config.name),
            ("Debug", "true" if self.app.config.debug else "false"),
            ("Base path", str(self.app.base_path)),
        ]
        self.out.line("[accent]Application[/accent]")
        self.out.definitions(rows)
        self.out.newline()

    def _print_database_section(self) -> None:
        try:
            from pylar.database import DatabaseConfig

            cfg = self.container.make(DatabaseConfig)
        except Exception:
            return
        self.out.line("[accent]Database[/accent]")
        self.out.definitions([
            ("URL", _mask_secrets(cfg.url)),
        ])
        self.out.newline()

    def _print_cache_section(self) -> None:
        try:
            from pylar.cache import Cache

            cache = self.container.make(Cache)
        except Exception:
            return
        store_name = type(getattr(cache, "_store", cache)).__name__
        self.out.line("[accent]Cache[/accent]")
        self.out.definitions([("Store", store_name)])
        self.out.newline()

    def _print_queue_section(self) -> None:
        try:
            from pylar.queue import JobQueue, QueuesConfig

            queue = self.container.make(JobQueue)  # type: ignore[type-abstract]
        except Exception:
            return
        driver = type(queue).__name__
        self.out.line("[accent]Queue[/accent]")
        defs: list[tuple[str, str]] = [("Driver", driver)]

        try:
            qcfg = self.container.make(QueuesConfig)
            summary = ", ".join(
                f"{name} ({c.min_workers}-{c.max_workers})"
                for name, c in qcfg.queues.items()
            )
            if summary:
                defs.append(("Queues", summary))
        except Exception:
            pass
        self.out.definitions(defs)
        self.out.newline()

    def _print_providers_section(self) -> None:
        providers = [p.__name__ for p in self.app.config.providers]
        if not providers:
            return
        self.out.line("[accent]Providers[/accent]")
        for name in providers:
            self.out.line(f"  {name}")
        self.out.newline()

    def _print_routes_section(self) -> None:
        try:
            from pylar.routing import Router

            router = self.container.make(Router)
        except Exception:
            return
        routes = router.routes()
        self.out.line("[accent]Routing[/accent]")
        self.out.definitions([("Registered routes", str(len(routes)))])
        self.out.newline()

    def _print_schedule_section(self) -> None:
        try:
            from pylar.scheduling import Schedule

            schedule = self.container.make(Schedule)
        except Exception:
            return
        tasks = schedule.tasks()
        if not tasks:
            return
        self.out.line("[accent]Scheduled tasks[/accent]")
        rows: list[tuple[str, ...]] = []
        for task in tasks:
            rows.append((task.cron_expression, task.name or task.describe()))
        self.out.table(
            headers=("Cron", "Task"),
            rows=rows,
        )
        self.out.newline()


def _mask_secrets(url: str) -> str:
    """Redact password in a DSN so ``pylar about`` is copy-pasteable."""
    import re

    return re.sub(r"://([^:/@]+):([^@]+)@", r"://\1:***@", url)


# Keep the tag registration co-located with the commands.
def register_commands(container: Container) -> None:
    from pylar.observability.doctor import DoctorCommand

    container.tag([AboutCommand, DoctorCommand], COMMANDS_TAG)
