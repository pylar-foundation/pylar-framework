"""Programmatic Alembic wrapper used by pylar's migration commands."""

from __future__ import annotations

import asyncio
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData

#: Where the bundled env.py / script.py.mako templates live inside pylar.
_TEMPLATE_DIR = Path(__file__).parent / "templates"

#: Laravel-style timestamp filename: ``2026_04_09_134523_create_posts.py``.
#:
#: ``%%`` escapes the percent sign for the configparser layer that backs
#: Alembic's main options; once configparser strips one level of escaping
#: Alembic itself runs the resulting ``%(year)d`` / ``%(slug)s`` template
#: through Python's ``%`` formatting against the dict it builds for each
#: revision.
_LARAVEL_FILE_TEMPLATE = (
    "%%(year)d_%%(month).2d_%%(day).2d_"
    "%%(hour).2d%%(minute).2d%%(second).2d_%%(slug)s"
)


class MigrationsRunner:
    """A thin async-friendly facade over :mod:`alembic.command`.

    Pylar deliberately avoids reimplementing migrations: Alembic is the
    industry-standard tool and its autogenerate feature is the killer
    capability we want to expose. The runner only owns the parts that pylar
    cares about — building the Alembic Config in memory, scaffolding the
    migrations directory on first use, and running the commands inside a
    worker thread so we never block the event loop.

    The constructor takes the database URL **as written by the user**
    (typically containing an async driver such as ``+aiosqlite``); the
    runner converts it to the corresponding sync driver before handing it
    to Alembic, because Alembic itself runs synchronously and the env.py
    template uses :func:`sqlalchemy.create_engine`.
    """

    def __init__(
        self,
        *,
        url: str,
        metadata: MetaData,
        migrations_path: Path,
    ) -> None:
        self._url = url
        self._metadata = metadata
        self._migrations_path = migrations_path

    @property
    def migrations_path(self) -> Path:
        return self._migrations_path

    # ----------------------------------------------------------------- commands

    async def upgrade(self, revision: str = "head", *, sql: bool = False) -> str | None:
        """Upgrade the database to *revision*.

        Set ``sql=True`` to run Alembic's offline mode and capture the
        SQL that *would* be issued without touching the database. The
        returned string is the SQL Alembic produced, ready to be diffed
        against migrations or piped into ``psql``.
        """
        if sql:
            return await asyncio.to_thread(
                self._capture_offline,
                command.upgrade,
                revision,
            )
        await asyncio.to_thread(command.upgrade, self._build_config(), revision)
        return None

    async def downgrade(self, revision: str = "-1", *, sql: bool = False) -> str | None:
        """Downgrade the database to *revision*.

        ``sql=True`` switches to Alembic's offline mode the same way
        :meth:`upgrade` does. Alembic's offline downgrade requires a
        ``<from>:<to>`` range — when the caller passes a single
        revision the runner expands it to ``head:<revision>`` so users
        do not have to think about the offline-mode quirk.
        """
        if sql:
            target = revision if ":" in revision else f"head:{revision}"
            return await asyncio.to_thread(
                self._capture_offline,
                command.downgrade,
                target,
            )
        await asyncio.to_thread(command.downgrade, self._build_config(), revision)
        return None

    async def revision(self, *, message: str, autogenerate: bool = True) -> None:
        await asyncio.to_thread(
            command.revision,
            self._build_config(),
            message=message,
            autogenerate=autogenerate,
        )

    async def current(self) -> str:
        """Return Alembic's textual ``current`` output."""
        return await asyncio.to_thread(self._capture_command, command.current)

    async def history(self) -> str:
        """Return Alembic's textual ``history`` output."""
        return await asyncio.to_thread(self._capture_command, command.history)

    async def status(self) -> list[dict[str, object]]:
        """Return structured migration status for every known revision.

        Each entry has: ``revision``, ``description``, ``is_applied``,
        ``is_head``, ``down_revision``. The list is ordered from newest
        to oldest (head first).
        """
        return await asyncio.to_thread(self._status_sync)

    def _status_sync(self) -> list[dict[str, object]]:
        from alembic.script import ScriptDirectory
        from sqlalchemy import create_engine, text

        config = self._build_config()
        script = ScriptDirectory.from_config(config)
        sync_url = _to_sync_url(self._url)
        engine = create_engine(sync_url)

        # Alembic stores only the *current* head revision(s) in
        # alembic_version — not the full history. Any revision that
        # is an ancestor of a stored head is also applied.
        current_heads: set[str] = set()
        try:
            with engine.connect() as conn:
                rows = conn.execute(text("SELECT version_num FROM alembic_version"))
                current_heads = {row[0] for row in rows}
        except Exception:
            pass  # Table doesn't exist yet — nothing applied.
        finally:
            engine.dispose()

        # Expand each current head to itself + every ancestor via
        # down_revision chains. That is the real set of applied revisions.
        applied: set[str] = set()
        for head in current_heads:
            for ancestor in script.iterate_revisions(head, "base"):
                applied.add(ancestor.revision)

        # Walk all revisions from head to base.
        result: list[dict[str, object]] = []
        for rev in script.walk_revisions():
            # Extract filename from the private _script_path attribute.
            script_path = getattr(rev, "_script_path", None)
            filename = Path(script_path).name if script_path else ""
            module = Path(script_path).stem if script_path else ""
            result.append({
                "revision": rev.revision,
                "description": rev.doc or "",
                "is_applied": rev.revision in applied,
                "is_head": rev.is_head,
                "down_revision": rev.down_revision,
                "filename": filename,
                "module": module,
            })
        return result

    async def drop_all(self) -> None:
        """Drop every table the bound metadata knows about.

        Used by ``migrate:fresh`` to reset the schema before reapplying
        migrations from scratch. Only the tables in :attr:`metadata` are
        dropped — anything created outside the metadata is left alone.
        """
        await asyncio.to_thread(self._drop_all_sync)

    # ------------------------------------------------------------------ internals

    def _build_config(self) -> Config:
        self._ensure_scaffold()
        # Alembic needs a ``script_location`` that contains ``env.py``
        # and ``script.py.mako``.  If the project ships its own copies
        # inside the migrations directory we use those (power-user
        # override); otherwise we point Alembic at pylar's built-in
        # templates so the user's project stays clean.
        if (self._migrations_path / "env.py").exists():
            script_location = str(self._migrations_path)
        else:
            script_location = str(_TEMPLATE_DIR)

        config = Config()
        config.set_main_option("script_location", script_location)
        # Migration revision files live directly under the project's
        # migrations_path — no ``versions/`` subfolder, matching
        # Laravel's flat layout.  Alembic's ``version_locations``
        # separates the script_location (env.py + template) from the
        # actual .py revisions.
        config.set_main_option("path_separator", "os")
        config.set_main_option(
            "version_locations", str(self._migrations_path)
        )
        config.set_main_option("file_template", _LARAVEL_FILE_TEMPLATE)
        config.attributes["target_metadata"] = self._metadata
        config.attributes["url"] = _to_sync_url(self._url)
        return config

    def _capture_command(self, alembic_command: Any) -> str:
        """Run an Alembic command that prints to stdout and capture the output."""
        buffer = StringIO()
        config = self._build_config()
        config.stdout = buffer
        alembic_command(config)
        return buffer.getvalue()

    def _capture_offline(self, alembic_command: Any, revision: str) -> str:
        """Run an Alembic up/downgrade in offline mode and return the SQL.

        Alembic's offline mode emits the SQL through ``sys.stdout``
        directly, ignoring the ``Config.stdout`` slot used by ``current``
        and ``history``. We therefore wrap the call in
        :func:`contextlib.redirect_stdout` so the SQL ends up in our
        buffer instead of escaping to the user's terminal.
        """
        buffer = StringIO()
        config = self._build_config()
        with redirect_stdout(buffer):
            alembic_command(config, revision, sql=True)
        return buffer.getvalue()

    def _drop_all_sync(self) -> None:
        """Drop every table in :attr:`metadata` plus Alembic's version table."""
        from sqlalchemy import create_engine

        sync_url = _to_sync_url(self._url)
        engine = create_engine(sync_url)
        try:
            self._metadata.drop_all(engine)
            # Alembic's bookkeeping table is not part of the user's metadata,
            # so the standard drop_all skips it. Drop it manually so the
            # next migrate run gets to start from a clean slate.
            with engine.begin() as conn:
                conn.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
        finally:
            engine.dispose()

    def _ensure_scaffold(self) -> None:
        """Create the migrations directory on first use.

        Unlike earlier versions, the runner no longer copies ``env.py``
        or ``script.py.mako`` into the project — pylar's built-in
        templates are used by default.  Users who need custom Alembic
        hooks can drop their own ``env.py`` / ``script.py.mako`` into
        the migrations directory and it will take priority.
        """
        self._migrations_path.mkdir(parents=True, exist_ok=True)


def _to_sync_url(url: str) -> str:
    """Replace an async SQLAlchemy driver with its synchronous counterpart.

    Alembic invokes the engine synchronously inside ``env.py``, so the URL we
    feed it must use a sync driver. Mappings cover the three drivers pylar
    currently supports out of the box; anything else is returned unchanged.
    """
    replacements = {
        "+aiosqlite": "",
        "+asyncpg": "+psycopg2",
        "+aiomysql": "+pymysql",
    }
    for async_driver, sync_driver in replacements.items():
        if async_driver in url:
            return url.replace(async_driver, sync_driver, 1)
    return url
