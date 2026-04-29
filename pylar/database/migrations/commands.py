"""Console commands that drive :class:`MigrationsRunner` and seeders.

All output goes through :class:`Output` (Rich-powered) for beautiful
terminal formatting. Destructive commands ask for interactive
confirmation via ``Output.confirm()`` when ``--force`` is not passed.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from pylar.console.command import Command
from pylar.console.output import Output
from pylar.database.connection import ConnectionManager
from pylar.database.migrations.runner import MigrationsRunner
from pylar.database.seeding import SEEDERS_TAG, Seeder
from pylar.database.session import use_session
from pylar.database.transaction import transaction
from pylar.foundation.container import Container

# ------------------------------------------------------------------- migrate


@dataclass(frozen=True)
class MigrateInput:
    target: str = field(
        default="head",
        metadata={"help": "Revision to upgrade to (default: head)"},
    )
    pretend: bool = field(
        default=False,
        metadata={"help": "Print the SQL that would be applied instead of running it"},
    )
    seed: bool = field(
        default=False,
        metadata={"help": "Run db:seed after a successful migration"},
    )


class MigrateCommand(Command[MigrateInput]):
    name = "migrate"
    description = "Apply pending database migrations"
    input_type = MigrateInput

    def __init__(
        self,
        runner: MigrationsRunner,
        container: Container,
        manager: ConnectionManager,
        output: Output,
    ) -> None:
        self.runner = runner
        self.container = container
        self.manager = manager
        self.out = output

    async def handle(self, input: MigrateInput) -> int:
        if input.pretend:
            sql = await self.runner.upgrade(input.target, sql=True)
            self.out.line(sql or "")
            return 0

        status = await self.runner.status()
        pending = [e for e in reversed(status) if not e["is_applied"]]
        if not pending:
            self.out.info("Nothing to migrate.")
            return 0

        self.out.newline()
        t0 = time.monotonic()
        await self.runner.upgrade(input.target)
        total_ms = (time.monotonic() - t0) * 1000

        for entry in pending:
            self.out.action("Running", str(entry["filename"]))

        self.out.newline()
        self.out.info(f"Ran {len(pending)} migration(s) in {total_ms:.2f}ms.")

        if input.seed:
            self.out.newline()
            seed_cmd = SeedCommand(self.container, self.manager, self.out)
            return await seed_cmd.handle(_SeedInput())
        return 0


# --------------------------------------------------------- migrate:rollback


@dataclass(frozen=True)
class MigrateRollbackInput:
    target: str = field(
        default="-1",
        metadata={"help": "Relative or absolute revision (default: -1, i.e. one step back)"},
    )
    pretend: bool = field(
        default=False,
        metadata={"help": "Print the SQL that would be issued instead of running it"},
    )


class MigrateRollbackCommand(Command[MigrateRollbackInput]):
    name = "migrate:rollback"
    description = "Roll back database migrations"
    input_type = MigrateRollbackInput

    def __init__(self, runner: MigrationsRunner, output: Output) -> None:
        self.runner = runner
        self.out = output

    async def handle(self, input: MigrateRollbackInput) -> int:
        if input.pretend:
            sql = await self.runner.downgrade(input.target, sql=True)
            self.out.line(sql or "")
            return 0

        status_before = await self.runner.status()
        applied_before = {str(e["revision"]) for e in status_before if e["is_applied"]}

        if not applied_before:
            self.out.info("Nothing to rollback.")
            return 0

        self.out.newline()
        t0 = time.monotonic()
        await self.runner.downgrade(input.target)
        total_ms = (time.monotonic() - t0) * 1000

        status_after = await self.runner.status()
        applied_after = {str(e["revision"]) for e in status_after if e["is_applied"]}
        rolled_back = applied_before - applied_after

        for entry in status_before:
            if str(entry["revision"]) in rolled_back:
                self.out.action("Rolling back", str(entry["filename"]))

        self.out.newline()
        self.out.info(f"Rolled back {len(rolled_back)} migration(s) in {total_ms:.2f}ms.")
        return 0


# --------------------------------------------------------------- migrate:fresh


@dataclass(frozen=True)
class MigrateFreshInput:
    force: bool = field(
        default=False,
        metadata={"help": "Skip interactive confirmation"},
    )
    seed: bool = field(
        default=False,
        metadata={"help": "Run db:seed after a successful fresh migration"},
    )


class MigrateFreshCommand(Command[MigrateFreshInput]):
    name = "migrate:fresh"
    description = "Drop every table and re-run all migrations from scratch"
    input_type = MigrateFreshInput

    def __init__(
        self,
        runner: MigrationsRunner,
        container: Container,
        manager: ConnectionManager,
        output: Output,
    ) -> None:
        self.runner = runner
        self.container = container
        self.manager = manager
        self.out = output

    async def handle(self, input: MigrateFreshInput) -> int:
        if not input.force:
            self.out.warn("This will drop ALL tables and re-run every migration.")
            if not self.out.confirm("Do you really wish to run this command?"):
                self.out.info("Command cancelled.")
                return 1

        self.out.newline()
        self.out.action("Dropping", "all tables")
        t0 = time.monotonic()
        await self.runner.drop_all()
        drop_ms = (time.monotonic() - t0) * 1000
        self.out.info(f"Dropped all tables in {drop_ms:.2f}ms.")

        self.out.newline()
        t1 = time.monotonic()
        await self.runner.upgrade("head")
        migrate_ms = (time.monotonic() - t1) * 1000

        status = await self.runner.status()
        for entry in reversed(status):
            self.out.action("Running", str(entry["filename"]))

        self.out.newline()
        self.out.info(f"Ran {len(status)} migration(s) in {migrate_ms:.2f}ms.")

        if input.seed:
            self.out.newline()
            seed_cmd = SeedCommand(
                container=self.container, manager=self.manager, output=self.out
            )
            return await seed_cmd.handle(_SeedInput())
        return 0


# ---------------------------------------------------------------- migrate:reset


@dataclass(frozen=True)
class MigrateResetInput:
    force: bool = field(
        default=False,
        metadata={"help": "Skip interactive confirmation"},
    )


class MigrateResetCommand(Command[MigrateResetInput]):
    name = "migrate:reset"
    description = "Roll every migration back to base"
    input_type = MigrateResetInput

    def __init__(self, runner: MigrationsRunner, output: Output) -> None:
        self.runner = runner
        self.out = output

    async def handle(self, input: MigrateResetInput) -> int:
        if not input.force:
            self.out.warn("This will roll back EVERY migration to base.")
            if not self.out.confirm("Do you really wish to run this command?"):
                self.out.info("Command cancelled.")
                return 1

        status_before = await self.runner.status()
        applied = [e for e in status_before if e["is_applied"]]

        if not applied:
            self.out.info("Nothing to rollback.")
            return 0

        self.out.newline()
        t0 = time.monotonic()
        await self.runner.downgrade("base")
        total_ms = (time.monotonic() - t0) * 1000

        for entry in applied:
            self.out.action("Rolling back", str(entry["filename"]))

        self.out.newline()
        self.out.info(f"Rolled back {len(applied)} migration(s) in {total_ms:.2f}ms.")
        return 0


# --------------------------------------------------------- migrate:refresh


@dataclass(frozen=True)
class MigrateRefreshInput:
    force: bool = field(
        default=False,
        metadata={"help": "Skip interactive confirmation"},
    )
    seed: bool = field(
        default=False,
        metadata={"help": "Run db:seed after refreshing"},
    )


class MigrateRefreshCommand(Command[MigrateRefreshInput]):
    """``pylar migrate:refresh`` — rollback all, then re-migrate."""

    name = "migrate:refresh"
    description = "Roll back all migrations, then re-run them"
    input_type = MigrateRefreshInput

    def __init__(
        self,
        runner: MigrationsRunner,
        container: Container,
        manager: ConnectionManager,
        output: Output,
    ) -> None:
        self.runner = runner
        self.container = container
        self.manager = manager
        self.out = output

    async def handle(self, input: MigrateRefreshInput) -> int:
        if not input.force:
            self.out.warn("This will roll back ALL migrations and re-run them.")
            if not self.out.confirm("Do you really wish to run this command?"):
                self.out.info("Command cancelled.")
                return 1

        status_before = await self.runner.status()
        applied_before = {str(e["revision"]) for e in status_before if e["is_applied"]}

        self.out.newline()
        t0 = time.monotonic()
        await self.runner.downgrade("base")
        rollback_ms = (time.monotonic() - t0) * 1000

        status_mid = await self.runner.status()
        applied_mid = {str(e["revision"]) for e in status_mid if e["is_applied"]}
        rolled_back_revs = applied_before - applied_mid

        for entry in status_before:
            if str(entry["revision"]) in rolled_back_revs:
                self.out.action("Rolling back", str(entry["filename"]))
        self.out.newline()
        if len(rolled_back_revs) != len(applied_before):
            self.out.warn(
                f"Expected to roll back {len(applied_before)}, "
                f"actually rolled back {len(rolled_back_revs)}. "
                f"Check that no other process is holding a DB lock."
            )
        self.out.info(
            f"Rolled back {len(rolled_back_revs)} migration(s) in {rollback_ms:.2f}ms."
        )

        self.out.newline()
        t1 = time.monotonic()
        await self.runner.upgrade("head")
        migrate_ms = (time.monotonic() - t1) * 1000

        status_after = await self.runner.status()
        applied_after = {str(e["revision"]) for e in status_after if e["is_applied"]}
        newly_applied = applied_after - applied_mid

        for entry in reversed(status_after):
            if str(entry["revision"]) in newly_applied:
                self.out.action("Running", str(entry["filename"]))
        self.out.newline()
        self.out.info(
            f"Ran {len(newly_applied)} migration(s) in {migrate_ms:.2f}ms."
        )

        if input.seed:
            self.out.newline()
            seed_cmd = SeedCommand(self.container, self.manager, self.out)
            return await seed_cmd.handle(_SeedInput())
        return 0


# ----------------------------------------------------------- migrate:status


@dataclass(frozen=True)
class _MigrateStatusInput:
    pass


class MigrateStatusCommand(Command[_MigrateStatusInput]):
    name = "migrate:status"
    description = "Show the current revision and migration history"
    input_type = _MigrateStatusInput

    def __init__(self, runner: MigrationsRunner, output: Output) -> None:
        self.runner = runner
        self.out = output

    async def handle(self, input: _MigrateStatusInput) -> int:
        entries = await self.runner.status()

        if not entries:
            self.out.info("No migrations found.")
            return 0

        rows: list[tuple[str, ...]] = []
        for entry in reversed(entries):
            marker = "[green]Yes[/green]" if entry["is_applied"] else "[yellow]No[/yellow]"
            rev = str(entry["revision"])
            filename = str(entry.get("filename", ""))
            desc = str(entry["description"])
            if entry["is_head"]:
                desc += " [cyan]\\[HEAD][/cyan]"
            rows.append((marker, rev, filename, desc))

        self.out.table(
            headers=("Ran?", "Revision", "Filename", "Description"),
            rows=rows,
            title="Migration Status",
        )

        total = len(entries)
        applied = sum(1 for e in entries if e["is_applied"])
        pending = total - applied
        self.out.newline()
        self.out.info(
            f"Total: {total} migration(s) — "
            f"[green]{applied} applied[/green], "
            f"[yellow]{pending} pending[/yellow]"
        )
        return 0


# ------------------------------------------------------------- make:migration


@dataclass(frozen=True)
class MakeMigrationInput:
    message: str = field(metadata={"help": "Short description of the change"})
    empty: bool = field(
        default=False,
        metadata={"help": "Skip autogenerate and create an empty revision skeleton"},
    )


class MakeMigrationCommand(Command[MakeMigrationInput]):
    name = "make:migration"
    description = "Create a new migration file (autogenerate by default)"
    input_type = MakeMigrationInput

    def __init__(self, runner: MigrationsRunner, output: Output) -> None:
        self.runner = runner
        self.out = output

    async def handle(self, input: MakeMigrationInput) -> int:
        await self.runner.revision(message=input.message, autogenerate=not input.empty)
        self.out.success(f"Created migration: {input.message}")
        return 0


# --------------------------------------------------------------------- db:seed


@dataclass(frozen=True)
class _SeedInput:
    """No arguments — runs every seeder registered under SEEDERS_TAG."""


class SeedCommand(Command[_SeedInput]):
    """``pylar db:seed`` — runs every registered :class:`Seeder` in order."""

    name = "db:seed"
    description = "Run every registered database seeder"
    input_type = _SeedInput

    def __init__(self, container: Container, manager: ConnectionManager, output: Output) -> None:
        self.container = container
        self.manager = manager
        self.out = output

    async def handle(self, input: _SeedInput) -> int:
        seeder_classes = self.container.tagged_types(SEEDERS_TAG)
        if not seeder_classes:
            self.out.info("No seeders registered.")
            return 0

        sorted_classes = sorted(
            seeder_classes,
            key=lambda cls: (getattr(cls, "__module__", ""), cls.__qualname__),
        )

        self.out.newline()
        async with use_session(self.manager):
            async with transaction():
                for cls in sorted_classes:
                    if not issubclass(cls, Seeder):
                        self.out.warn(
                            f"{cls.__qualname__} is tagged as a seeder but is "
                            f"not a Seeder subclass; skipping."
                        )
                        continue
                    t0 = time.monotonic()
                    instance = self.container.make(cls)
                    self.out.action("Seeding", cls.__qualname__)
                    await instance.run()
                    ms = (time.monotonic() - t0) * 1000
                    self.out.action("Seeded", cls.__qualname__, duration_ms=ms)

        self.out.newline()
        self.out.info(f"Ran {len(sorted_classes)} seeder(s).")
        return 0
