"""Smoke tests for every console command.

Boots a full application and verifies that every registered command:
1. Is discoverable in the command index
2. Can be instantiated by the container without errors
3. Handles a basic invocation without crashing

These are NOT unit tests for command logic — those live alongside each
module. This file catches wiring failures (missing bindings, signature
mismatches, circular imports) that only surface with a real container.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import ClassVar

import pytest

from pylar.cache import CacheServiceProvider
from pylar.console.builtin import HelpCommand, ListCommand
from pylar.console.kernel import COMMANDS_TAG, ConsoleKernel
from pylar.console.make import MakeServiceProvider
from pylar.console.output import BufferedOutput
from pylar.console.tinker import TinkerCommand
from pylar.database import DatabaseConfig, DatabaseServiceProvider, Model
from pylar.database.connection import ConnectionManager
from pylar.database.migrations import MigrationsServiceProvider
from pylar.encryption import EncryptionServiceProvider
from pylar.foundation import AppConfig, Application
from pylar.foundation.commands import PackageListCommand
from pylar.http import HttpServiceProvider
from pylar.routing import Router
from pylar.routing.commands import RouteListCommand, RouteListInput
from pylar.session import SessionServiceProvider
from pylar.storage import StorageServiceProvider
from pylar.views import ViewServiceProvider

# ---------------------------------------------------------- fixtures


@pytest.fixture
async def app() -> AsyncIterator[Application]:
    """A fully bootstrapped application with all framework providers."""
    application = Application(
        base_path=Path("/tmp/pylar-smoke-test"),
        config=AppConfig(
            name="smoke-test",
            debug=True,
            autodiscover=False,
            providers=(
                DatabaseServiceProvider,
                MigrationsServiceProvider,
                CacheServiceProvider,
                EncryptionServiceProvider,
                SessionServiceProvider,
                StorageServiceProvider,
                HttpServiceProvider,
                ViewServiceProvider,
                MakeServiceProvider,
            ),
        ),
    )
    application.container.instance(
        DatabaseConfig,
        DatabaseConfig(url="sqlite+aiosqlite:///:memory:"),
    )
    from pylar.storage import StorageConfig

    application.container.instance(
        StorageConfig, StorageConfig(root="/tmp/pylar-smoke-test/storage")
    )
    await application.bootstrap()

    # Create tables so migrate:status etc. don't fail.
    mgr = application.container.make(ConnectionManager)
    async with mgr.engine.begin() as conn:
        await conn.run_sync(Model.metadata.create_all)

    # Register builtin commands (list, help, tinker, package:list).
    kernel = ConsoleKernel(app=application, argv=[])
    kernel._register_builtin_commands()

    yield application
    await application.shutdown()


# ------------------------------------------------- command discovery


class TestCommandDiscovery:
    """Verify all expected commands are registered."""

    EXPECTED_COMMANDS: ClassVar[set[str]] = {
        # Builtins
        "list",
        "help",
        "tinker",
        "package:list",
        # HTTP
        "serve",
        "down",
        "up",
        # Routing
        "route:list",
        # Cache
        "cache:clear",
        # Encryption
        "key:generate",
        # Migrations
        "migrate",
        "migrate:rollback",
        "migrate:fresh",
        "migrate:refresh",
        "migrate:reset",
        "migrate:status",
        "make:migration",
        "db:seed",
        # Make generators (16)
        "make:model",
        "make:controller",
        "make:provider",
        "make:command",
        "make:dto",
        "make:job",
        "make:event",
        "make:listener",
        "make:policy",
        "make:mailable",
        "make:notification",
        "make:factory",
        "make:observer",
        "make:middleware",
        "make:test",
        "make:seeder",
    }

    def test_all_commands_registered(self, app: Application) -> None:
        """Every expected command name appears in the tagged command index."""
        tagged = app.container.tagged_types(COMMANDS_TAG)
        registered_names = {
            cls.name for cls in tagged if hasattr(cls, "name") and cls.name
        }
        missing = self.EXPECTED_COMMANDS - registered_names
        assert not missing, f"Commands not registered: {missing}"

    def test_command_count(self, app: Application) -> None:
        """Sanity check: at least 34 commands with the base providers."""
        tagged = app.container.tagged_types(COMMANDS_TAG)
        assert len(tagged) >= 34


# ------------------------------------------------ command instantiation


class TestCommandInstantiation:
    """Verify every command can be constructed by the container."""

    def test_all_commands_instantiable(self, app: Application) -> None:
        """The container can make() every registered command class."""
        tagged = app.container.tagged_types(COMMANDS_TAG)
        failures: list[str] = []
        for cls in tagged:
            try:
                app.container.make(cls)
            except Exception as exc:
                failures.append(f"{cls.__qualname__}: {exc}")
        if failures:
            report = "\n".join(failures)
            raise AssertionError(
                f"Commands that failed to instantiate:\n{report}"
            )


# ------------------------------------------------ smoke-run commands


class TestCommandSmokeRun:
    """Run commands with safe inputs and verify they return exit code 0."""

    async def test_list_command(
        self, app: Application, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cmd: ListCommand = app.container.make(ListCommand)
        from pylar.console.builtin import _ListInput

        code = await cmd.handle(_ListInput())
        assert code == 0
        output = capsys.readouterr().out
        assert "list" in output
        assert "migrate" in output

    async def test_help_command(self, app: Application) -> None:
        cmd: HelpCommand = app.container.make(HelpCommand)
        from pylar.console.builtin import _HelpInput

        code = await cmd.handle(_HelpInput(command="list"))
        assert code == 0

    async def test_route_list_command(self, app: Application) -> None:
        out = BufferedOutput()
        router = app.container.make(Router)
        cmd = RouteListCommand(router, out)
        code = await cmd.handle(RouteListInput())
        assert code == 0

    async def test_cache_clear_command(self, app: Application) -> None:
        from pylar.cache.commands import CacheClearCommand, CacheClearInput

        cmd: CacheClearCommand = app.container.make(CacheClearCommand)
        code = await cmd.handle(CacheClearInput())
        assert code == 0

    async def test_key_generate_command(self, app: Application) -> None:
        from pylar.encryption.commands import KeyGenerateCommand, _KeyGenInput

        cmd: KeyGenerateCommand = app.container.make(KeyGenerateCommand)
        code = await cmd.handle(_KeyGenInput())
        assert code == 0

    async def test_migrate_status_command(self, app: Application) -> None:
        from pylar.database.migrations.commands import (
            MigrateStatusCommand,
            _MigrateStatusInput,
        )

        out = BufferedOutput()
        from pylar.database.migrations import MigrationsRunner

        runner = app.container.make(MigrationsRunner)
        cmd = MigrateStatusCommand(runner, out)
        code = await cmd.handle(_MigrateStatusInput())
        assert code == 0

    async def test_package_list_command(self, app: Application) -> None:
        from pylar.foundation.commands import _PackageListInput

        cmd: PackageListCommand = app.container.make(PackageListCommand)
        code = await cmd.handle(_PackageListInput())
        assert code == 0

    async def test_tinker_namespace(self, app: Application) -> None:
        """Tinker builds a namespace without errors."""
        cmd = TinkerCommand(app=app, container=app.container)
        ns = cmd._build_namespace()
        assert "app" in ns
        assert "container" in ns
        assert "Q" in ns
        assert "F" in ns
        assert "transaction" in ns

    async def test_schedule_list_command(self, app: Application) -> None:
        from pylar.scheduling.commands import ScheduleListCommand, _ScheduleListInput

        cmd: ScheduleListCommand = app.container.make(ScheduleListCommand)
        code = await cmd.handle(_ScheduleListInput())
        assert code == 0

    async def test_make_commands_parse_without_error(self, app: Application) -> None:
        """Every make:* command can parse its --help without crashing."""
        from pylar.console.make.commands import ALL_MAKE_COMMANDS

        for cmd_cls in ALL_MAKE_COMMANDS:
            parser = cmd_cls.parser()
            assert parser is not None
            assert cmd_cls.name.startswith("make:")
