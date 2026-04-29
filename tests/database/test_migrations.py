"""End-to-end tests for :class:`MigrationsRunner` and the migration commands.

The tests use an isolated SQLAlchemy :class:`MetaData` so that they do not
collide with the ``test_users`` table from ``conftest.py``. Each test runs
against a fresh aiosqlite file inside ``tmp_path`` and a fresh migrations
directory under ``tmp_path / "database" / "migrations"``.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table

from pylar.database.migrations import MigrationsRunner
from pylar.database.migrations.runner import _to_sync_url


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
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
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


# ----------------------------------------------------------------- url helpers


def test_to_sync_url_strips_aiosqlite() -> None:
    assert _to_sync_url("sqlite+aiosqlite:///./db.sqlite") == "sqlite:///./db.sqlite"


def test_to_sync_url_swaps_asyncpg_for_psycopg2() -> None:
    assert _to_sync_url("postgresql+asyncpg://u:p@h/db") == "postgresql+psycopg2://u:p@h/db"


def test_to_sync_url_passes_unknown_drivers_through() -> None:
    assert _to_sync_url("sqlite:///x") == "sqlite:///x"


# ------------------------------------------------------------------- scaffold


async def test_first_revision_creates_scaffold_files(runner: MigrationsRunner) -> None:
    await runner.revision(message="initial widgets table")

    migrations = runner.migrations_path
    # env.py and script.py.mako are no longer copied into the project —
    # pylar ships built-in defaults. The user's directory only contains
    # the actual revision files.
    assert migrations.is_dir()

    revisions = list(migrations.glob("*.py"))
    assert len(revisions) == 1, f"expected exactly one revision file, got {revisions}"


async def test_revision_filename_uses_laravel_timestamp_format(
    runner: MigrationsRunner,
) -> None:
    await runner.revision(message="add widgets")
    revisions = list(runner.migrations_path.glob("*.py"))
    assert len(revisions) == 1
    name = revisions[0].name
    # YYYY_MM_DD_HHMMSS_<slug>.py
    assert re.match(
        r"^\d{4}_\d{2}_\d{2}_\d{6}_add_widgets\.py$", name
    ), f"unexpected filename {name!r}"


# ------------------------------------------------------------- end-to-end flow


async def test_autogenerate_creates_table_after_upgrade(
    runner: MigrationsRunner, tmp_path: Path
) -> None:
    await runner.revision(message="add widgets")
    await runner.upgrade("head")

    db_file = tmp_path / "test.db"
    assert _table_exists(db_file, "widgets")


async def test_downgrade_removes_table(
    runner: MigrationsRunner, tmp_path: Path
) -> None:
    await runner.revision(message="add widgets")
    await runner.upgrade("head")
    await runner.downgrade("base")

    db_file = tmp_path / "test.db"
    assert not _table_exists(db_file, "widgets")


async def test_current_reports_head_after_upgrade(
    runner: MigrationsRunner,
) -> None:
    await runner.revision(message="add widgets")
    await runner.upgrade("head")

    output = await runner.current()
    # Alembic prints the revision id followed by "(head)"
    assert "(head)" in output


async def test_history_lists_revision(runner: MigrationsRunner) -> None:
    await runner.revision(message="add widgets")
    history = await runner.history()
    assert "add widgets" in history


# ----------------------------------------------- autogenerate model evolution


async def test_autogenerate_detects_added_column(tmp_path: Path) -> None:
    """End-to-end proof that ``make:migration`` follows model edits.

    The flow mirrors what a user does in real life:

    1. Define a model, generate a revision, upgrade. The DB schema now
       matches the model.
    2. Add a column to the model. Generate another revision against
       the *upgraded* DB. Alembic's autogenerate compares the new
       metadata to the live database and emits ``op.add_column`` for
       the difference.
    """
    db_file = tmp_path / "evolution.db"
    migrations = tmp_path / "database" / "migrations"
    url = f"sqlite+aiosqlite:///{db_file}"

    # Step 1 — initial schema with a single column.
    metadata_v1 = MetaData()
    Table("gadgets", metadata_v1, Column("id", Integer, primary_key=True))

    runner_v1 = MigrationsRunner(url=url, metadata=metadata_v1, migrations_path=migrations)
    await runner_v1.revision(message="create gadgets")
    await runner_v1.upgrade("head")

    # Sanity: the column exists, the new one does not yet.
    with sqlite3.connect(db_file) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(gadgets)")}
    assert columns == {"id"}

    # Step 2 — model evolves: add `name`.
    metadata_v2 = MetaData()
    Table(
        "gadgets",
        metadata_v2,
        Column("id", Integer, primary_key=True),
        Column("name", String(120), nullable=False, server_default="anon"),
    )
    runner_v2 = MigrationsRunner(url=url, metadata=metadata_v2, migrations_path=migrations)
    before = set(migrations.glob("*.py"))
    await runner_v2.revision(message="add gadget name")
    after = set(migrations.glob("*.py"))
    new_files = after - before
    assert len(new_files) == 1, f"expected one new revision, got {new_files}"
    second = new_files.pop().read_text(encoding="utf-8")
    assert "add_column" in second
    assert "name" in second

    # Apply the second revision and verify the column lands.
    await runner_v2.upgrade("head")
    with sqlite3.connect(db_file) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(gadgets)")}
    assert columns == {"id", "name"}


async def test_autogenerate_detects_dropped_column(tmp_path: Path) -> None:
    """Symmetric: removing a column from the model produces ``drop_column``."""
    db_file = tmp_path / "shrink.db"
    migrations = tmp_path / "database" / "migrations"
    url = f"sqlite+aiosqlite:///{db_file}"

    metadata_v1 = MetaData()
    Table(
        "items",
        metadata_v1,
        Column("id", Integer, primary_key=True),
        Column("note", String(120)),
    )
    runner_v1 = MigrationsRunner(url=url, metadata=metadata_v1, migrations_path=migrations)
    await runner_v1.revision(message="create items")
    await runner_v1.upgrade("head")

    metadata_v2 = MetaData()
    Table("items", metadata_v2, Column("id", Integer, primary_key=True))
    runner_v2 = MigrationsRunner(url=url, metadata=metadata_v2, migrations_path=migrations)
    before = set(migrations.glob("*.py"))
    await runner_v2.revision(message="drop items note")
    after = set(migrations.glob("*.py"))
    new_files = after - before
    assert len(new_files) == 1
    second = new_files.pop().read_text(encoding="utf-8")
    assert "drop_column" in second
    assert "note" in second


# ------------------------------------------------------------------ commands


@pytest.fixture(autouse=True)
def _isolate_global_metadata() -> None:
    """Detach Model from any tables created by other test modules.

    The migration commands resolve ``Model.metadata`` from the application
    container; tests in this module work with their own metadata, so this
    fixture is a no-op safety net to make the order-independence intent
    explicit.
    """


async def test_migrate_command_runs_runner(
    runner: MigrationsRunner, tmp_path: Path
) -> None:
    from pylar.console.output import Output as _Out
    from pylar.database.migrations.commands import (
        MakeMigrationCommand,
        MakeMigrationInput,
        MigrateCommand,
        MigrateInput,
    )
    make_cmd = MakeMigrationCommand(runner, _Out(colour=False))
    code = await make_cmd.handle(MakeMigrationInput(message="add widgets", empty=False))
    assert code == 0

    from pylar.database import ConnectionManager, DatabaseConfig
    from pylar.foundation.container import Container

    container = Container()
    config = DatabaseConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    mgr = ConnectionManager(config)
    await mgr.initialize()

    from pylar.console.output import Output
    migrate_cmd = MigrateCommand(runner, container, mgr, Output(colour=False))
    code = await migrate_cmd.handle(MigrateInput(target="head"))
    assert code == 0

    assert _table_exists(tmp_path / "test.db", "widgets")
    await mgr.dispose()


async def test_rollback_command_unwinds_one_step(
    runner: MigrationsRunner, tmp_path: Path
) -> None:
    from pylar.database.migrations.commands import (
        MigrateRollbackCommand,
        MigrateRollbackInput,
    )

    await runner.revision(message="add widgets")
    await runner.upgrade("head")
    assert _table_exists(tmp_path / "test.db", "widgets")

    from pylar.console.output import Output
    rollback = MigrateRollbackCommand(runner, Output(colour=False))
    code = await rollback.handle(MigrateRollbackInput(target="base"))
    assert code == 0
    assert not _table_exists(tmp_path / "test.db", "widgets")


async def test_rollback_command_noop_on_empty_db(
    runner: MigrationsRunner, tmp_path: Path
) -> None:
    from pylar.console.output import Output
    from pylar.database.migrations.commands import (
        MigrateRollbackCommand,
        MigrateRollbackInput,
    )

    await runner.revision(message="add widgets")

    rollback = MigrateRollbackCommand(runner, Output(colour=False))
    code = await rollback.handle(MigrateRollbackInput())
    assert code == 0
