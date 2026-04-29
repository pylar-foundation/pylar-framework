"""Tests for the second migrations batch: fresh, reset, --pretend, db:seed."""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table

from pylar.console.output import Output
from pylar.database import (
    SEEDERS_TAG,
    ConnectionManager,
    DatabaseConfig,
    DatabaseServiceProvider,
    Seeder,
)
from pylar.database.migrations import MigrationsRunner
from pylar.database.migrations.commands import (
    MigrateCommand,
    MigrateFreshCommand,
    MigrateFreshInput,
    MigrateInput,
    MigrateResetCommand,
    MigrateResetInput,
    MigrateRollbackCommand,
    MigrateRollbackInput,
    SeedCommand,
    _SeedInput,
)
from pylar.foundation import (
    AppConfig,
    Application,
    Container,
    ServiceProvider,
)

# Output that writes to sys.stdout so capsys can capture it.
_out = Output(colour=False)


# --------------------------------------------------------------- helpers


def _build_metadata() -> MetaData:
    metadata = MetaData()
    Table(
        "widgets",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("name", String(120), nullable=False),
    )
    return metadata


def _table_exists(db_path: Path, name: str) -> bool:
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        )
        return cursor.fetchone() is not None


@pytest.fixture
def runner(tmp_path: Path) -> MigrationsRunner:
    db_file = tmp_path / "test.db"
    return MigrationsRunner(
        url=f"sqlite+aiosqlite:///{db_file}",
        metadata=_build_metadata(),
        migrations_path=tmp_path / "database" / "migrations",
    )


# ----------------------------------------------------------- migrate --pretend


async def test_migrate_pretend_returns_sql_without_running(
    runner: MigrationsRunner, tmp_path: Path
) -> None:
    await runner.revision(message="add widgets")

    sql = await runner.upgrade("head", sql=True)
    assert sql is not None
    assert "CREATE TABLE" in sql
    # Offline mode did not touch the database file.
    assert not _table_exists(tmp_path / "test.db", "widgets")


async def test_migrate_command_pretend_prints_sql(
    runner: MigrationsRunner,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    await runner.revision(message="add widgets")

    from pylar.database import ConnectionManager, DatabaseConfig
    from pylar.foundation.container import Container

    container = Container()
    config = DatabaseConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    mgr = ConnectionManager(config)
    await mgr.initialize()

    cmd = MigrateCommand(runner, container, mgr, _out)
    code = await cmd.handle(MigrateInput(target="head", pretend=True))
    assert code == 0
    out = capsys.readouterr().out
    assert "CREATE TABLE" in out
    assert not _table_exists(tmp_path / "test.db", "widgets")
    await mgr.dispose()


async def test_rollback_command_pretend_prints_sql(
    runner: MigrationsRunner,
    capsys: pytest.CaptureFixture[str],
) -> None:
    await runner.revision(message="add widgets")
    await runner.upgrade("head")
    capsys.readouterr()

    cmd = MigrateRollbackCommand(runner, _out)
    code = await cmd.handle(MigrateRollbackInput(target="base", pretend=True))
    assert code == 0
    out = capsys.readouterr().out
    assert "DROP TABLE" in out


# ----------------------------------------------------------- migrate:fresh


async def test_fresh_requires_force_flag(
    runner: MigrationsRunner,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    await runner.revision(message="add widgets")
    await runner.upgrade("head")
    assert _table_exists(tmp_path / "test.db", "widgets")

    cmd = MigrateFreshCommand(
        runner=runner, container=Container(), manager=runner, output=_out  # type: ignore[arg-type]
    )
    # Without --force, the command asks for interactive confirmation.
    # In tests stdin is not a tty so _confirm returns False → cancelled.
    code = await cmd.handle(MigrateFreshInput(force=False))
    assert code == 1
    out = capsys.readouterr().out
    assert "cancelled" in out.lower() or "cancel" in out.lower()
    # Table still around — refusal preserved state.
    assert _table_exists(tmp_path / "test.db", "widgets")


async def test_fresh_drops_then_remigrates(
    runner: MigrationsRunner, tmp_path: Path
) -> None:
    await runner.revision(message="add widgets")
    await runner.upgrade("head")

    # Insert a row to prove the table really gets dropped.
    db_file = tmp_path / "test.db"
    with sqlite3.connect(db_file) as conn:
        conn.execute("INSERT INTO widgets (id, name) VALUES (1, 'sample')")
        conn.commit()

    cmd = MigrateFreshCommand(
        runner=runner, container=Container(), manager=runner, output=_out  # type: ignore[arg-type]
    )
    code = await cmd.handle(MigrateFreshInput(force=True))
    assert code == 0

    assert _table_exists(db_file, "widgets")
    with sqlite3.connect(db_file) as conn:
        rows = list(conn.execute("SELECT COUNT(*) FROM widgets"))
        assert rows == [(0,)]


# ----------------------------------------------------------- migrate:reset


async def test_reset_requires_force_flag(
    runner: MigrationsRunner,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cmd = MigrateResetCommand(runner, _out)
    # Without --force, interactive confirmation is required.
    # In tests stdin is not a tty so _confirm returns False → cancelled.
    code = await cmd.handle(MigrateResetInput(force=False))
    assert code == 1
    out = capsys.readouterr().out
    assert "cancelled" in out.lower() or "cancel" in out.lower()


async def test_reset_rolls_everything_back(
    runner: MigrationsRunner, tmp_path: Path
) -> None:
    await runner.revision(message="add widgets")
    await runner.upgrade("head")
    db_file = tmp_path / "test.db"
    assert _table_exists(db_file, "widgets")

    cmd = MigrateResetCommand(runner, _out)
    code = await cmd.handle(MigrateResetInput(force=True))
    assert code == 0
    assert not _table_exists(db_file, "widgets")


# --------------------------------------------------------------------- db:seed


_SEED_LOG: list[str] = []


class _RecordingSeeder(Seeder):
    def __init__(self) -> None:
        self.label = "first"

    async def run(self) -> None:
        _SEED_LOG.append(self.label)


class _SecondSeeder(Seeder):
    async def run(self) -> None:
        _SEED_LOG.append("second")


class _ConfigProvider(ServiceProvider):
    def register(self, container: Container) -> None:
        container.instance(
            DatabaseConfig,
            DatabaseConfig(url="sqlite+aiosqlite:///:memory:"),
        )


class _SeederProvider(ServiceProvider):
    def register(self, container: Container) -> None:
        container.tag([_RecordingSeeder, _SecondSeeder], SEEDERS_TAG)


@pytest.fixture(autouse=True)
def _reset_seed_log() -> None:
    _SEED_LOG.clear()


@pytest.fixture
async def app() -> AsyncIterator[Application]:
    application = Application(
        base_path=Path("/tmp/pylar-seed-test"),
        config=AppConfig(
            name="seed-test",
            debug=True,
            providers=(_ConfigProvider, DatabaseServiceProvider, _SeederProvider),
        ),
    )
    await application.bootstrap()
    yield application
    await application.shutdown()


async def test_seed_command_runs_every_registered_seeder(
    app: Application, capsys: pytest.CaptureFixture[str]
) -> None:
    container = app.container
    manager = container.make(ConnectionManager)
    cmd = SeedCommand(container, manager, _out)

    code = await cmd.handle(_SeedInput())
    assert code == 0
    assert _SEED_LOG == ["first", "second"]
    out = capsys.readouterr().out
    assert "_RecordingSeeder" in out
    assert "_SecondSeeder" in out
    assert "2 seeder" in out


async def test_seed_command_no_op_when_nothing_registered(
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = Application(
        base_path=Path("/tmp/pylar-seed-empty"),
        config=AppConfig(
            name="seed-empty",
            debug=True,
            providers=(_ConfigProvider, DatabaseServiceProvider),
        ),
    )
    await application.bootstrap()
    try:
        manager = application.container.make(ConnectionManager)
        cmd = SeedCommand(application.container, manager, _out)
        code = await cmd.handle(_SeedInput())
        assert code == 0
        assert "No seeders registered" in capsys.readouterr().out
    finally:
        await application.shutdown()
