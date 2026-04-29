"""``pylar doctor`` — probe every bound resource and report a pass/fail table.

Intended as a CI-friendly readiness gate: every check returns a
:class:`CheckResult` and the command exits non-zero if any check
fails. Unbound resources are skipped (``-`` in the output), not
failed — ``pylar doctor`` is opinionated about liveness, not about
what the user *should* wire up.

Adding a new check is a matter of dropping an ``async def _check_foo``
method below and extending :meth:`DoctorCommand._all_checks`. Each
check has its own try/except envelope so one failing integration
never obscures the others.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

from pylar.console.command import Command
from pylar.console.output import Output
from pylar.foundation.container import Container

_Status = Literal["pass", "fail", "skip"]


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    status: _Status
    detail: str = ""


@dataclass(frozen=True)
class _DoctorInput:
    """No arguments — runs every registered check."""


class DoctorCommand(Command[_DoctorInput]):
    """Probe database, cache, queue, storage, mail, migrations."""

    name = "doctor"
    description = "Probe every bound resource and report a readiness table"
    input_type = _DoctorInput

    def __init__(self, container: Container, output: Output) -> None:
        self.container = container
        self.out = output

    async def handle(self, input: _DoctorInput) -> int:
        self.out.newline()
        self.out.line("[accent]Doctor[/accent] — probing bound resources")
        self.out.newline()

        checks = await self._all_checks()
        failed = 0
        for result in checks:
            self._print_result(result)
            if result.status == "fail":
                failed += 1

        self.out.newline()
        if failed:
            self.out.error(f"{failed} check(s) failed.")
            return 1
        self.out.success("All checks passed.")
        return 0

    # --------------------------------------------------------------- checks

    async def _all_checks(self) -> list[CheckResult]:
        return [
            await self._check_database(),
            await self._check_cache(),
            await self._check_queue(),
            await self._check_storage(),
            await self._check_mail(),
            await self._check_migrations(),
        ]

    async def _check_database(self) -> CheckResult:
        try:
            from pylar.database.connection import ConnectionManager
        except Exception:
            return CheckResult("Database", "skip", "pylar.database not installed")
        if not self.container.has(ConnectionManager):
            return CheckResult("Database", "skip", "ConnectionManager not bound")
        try:
            from sqlalchemy import text

            manager = self.container.make(ConnectionManager)
            start = time.monotonic()
            async with manager.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            ms = (time.monotonic() - start) * 1000
            return CheckResult("Database", "pass", f"SELECT 1 in {ms:.1f}ms")
        except Exception as exc:
            return CheckResult("Database", "fail", _short(exc))

    async def _check_cache(self) -> CheckResult:
        try:
            from pylar.cache import Cache
        except Exception:
            return CheckResult("Cache", "skip", "pylar.cache not installed")
        if not self.container.has(Cache):
            return CheckResult("Cache", "skip", "Cache not bound")
        try:
            cache = self.container.make(Cache)
            start = time.monotonic()
            await cache.put("__pylar_doctor__", "ok", ttl=5)
            value = await cache.get("__pylar_doctor__")
            await cache.forget("__pylar_doctor__")
            ms = (time.monotonic() - start) * 1000
            if value != "ok":
                return CheckResult("Cache", "fail", "round-trip mismatch")
            return CheckResult("Cache", "pass", f"round-trip {ms:.1f}ms")
        except Exception as exc:
            return CheckResult("Cache", "fail", _short(exc))

    async def _check_queue(self) -> CheckResult:
        try:
            from pylar.queue import JobQueue
        except Exception:
            return CheckResult("Queue", "skip", "pylar.queue not installed")
        if not self.container.has(JobQueue):
            return CheckResult("Queue", "skip", "JobQueue not bound")
        try:
            queue = self.container.make(JobQueue)  # type: ignore[type-abstract]
            size = await queue.size("default")
            driver = type(queue).__name__
            return CheckResult(
                "Queue", "pass", f"{driver} size(default)={size}"
            )
        except Exception as exc:
            return CheckResult("Queue", "fail", _short(exc))

    async def _check_storage(self) -> CheckResult:
        try:
            from pylar.storage import FilesystemStore
        except Exception:
            return CheckResult("Storage", "skip", "pylar.storage not installed")
        if not self.container.has(FilesystemStore):
            return CheckResult("Storage", "skip", "FilesystemStore not bound")
        try:
            store = self.container.make(FilesystemStore)  # type: ignore[type-abstract]
            driver = type(store).__name__
            return CheckResult("Storage", "pass", driver)
        except Exception as exc:
            return CheckResult("Storage", "fail", _short(exc))

    async def _check_mail(self) -> CheckResult:
        try:
            from pylar.mail import Mailer
        except Exception:
            return CheckResult("Mail", "skip", "pylar.mail not installed")
        if not self.container.has(Mailer):
            return CheckResult("Mail", "skip", "Mailer not bound")
        try:
            mailer = self.container.make(Mailer)
            transport = type(getattr(mailer, "_transport", mailer)).__name__
            return CheckResult("Mail", "pass", f"transport={transport}")
        except Exception as exc:
            return CheckResult("Mail", "fail", _short(exc))

    async def _check_migrations(self) -> CheckResult:
        try:
            from pylar.database.migrations import MigrationsRunner
        except Exception:
            return CheckResult("Migrations", "skip", "migrations not installed")
        if not self.container.has(MigrationsRunner):
            return CheckResult("Migrations", "skip", "MigrationsRunner not bound")
        try:
            runner = self.container.make(MigrationsRunner)
            status = await runner.status()
            pending = [e for e in status if not e["is_applied"]]
            if pending:
                return CheckResult(
                    "Migrations", "fail",
                    f"{len(pending)} pending migration(s)",
                )
            return CheckResult("Migrations", "pass", "up to date")
        except Exception as exc:
            return CheckResult("Migrations", "fail", _short(exc))

    # ---------------------------------------------------------- rendering

    def _print_result(self, result: CheckResult) -> None:
        mark, style = _marks[result.status]
        detail = f" — {result.detail}" if result.detail else ""
        self.out.line(
            f"  [{style}]{mark}[/{style}] {result.name:<14}{detail}"
        )


_marks: dict[_Status, tuple[str, str]] = {
    "pass": ("✓", "success"),
    "fail": ("✗", "error"),
    "skip": ("-", "muted"),
}


def _short(exc: Exception) -> str:
    msg = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
    return msg[:120]
