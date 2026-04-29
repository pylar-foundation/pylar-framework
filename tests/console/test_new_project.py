"""Smoke tests for ``pylar new`` project scaffolding."""

from __future__ import annotations

import ast
import os
from pathlib import Path

from pylar.console.new_project import new_project


def test_scaffold_creates_expected_layout(tmp_path: Path) -> None:
    """The command creates a complete directory tree with a project name."""
    os.chdir(tmp_path)
    rc = new_project(["myblog"])
    assert rc == 0

    root = tmp_path / "myblog"
    # Core directories.
    for d in (
        "app/http/controllers",
        "app/models",
        "app/providers",
        "config",
        "database/migrations",
        "routes",
        "resources/views",
    ):
        assert (root / d).is_dir(), f"missing: {d}"


def test_scaffold_config_app_parses_and_lists_new_providers(
    tmp_path: Path,
) -> None:
    """The generated config/app.py is syntactically valid Python and includes
    the providers mentioned in the C4 checklist."""
    os.chdir(tmp_path)
    assert new_project(["myblog"]) == 0

    config = (tmp_path / "myblog" / "config" / "app.py").read_text("utf-8")
    # Must parse as Python.
    ast.parse(config)
    # Must reference the new-from-C4 providers.
    for provider in (
        "ApiServiceProvider",
        "ObservabilityServiceProvider",
        "QueueServiceProvider",
    ):
        assert provider in config, f"{provider} missing from generated config/app.py"


def test_scaffold_is_idempotent_guard(tmp_path: Path) -> None:
    """Running twice with the same name must refuse rather than overwrite."""
    os.chdir(tmp_path)
    assert new_project(["myblog"]) == 0
    assert new_project(["myblog"]) == 1  # second call fails


def test_scaffold_ships_all_system_migrations(tmp_path: Path) -> None:
    """Every framework feature with persisted state has a migration stub.

    Laravel ships a bundle of migrations with every fresh project
    (users, password_reset_tokens, failed_jobs, cache, jobs, sessions,
    personal_access_tokens). Pylar mirrors that model so features like
    API tokens, roles, the database queue, the database cache, and the
    notifications channel are usable out of the box without manual
    migration writing.
    """
    os.chdir(tmp_path)
    assert new_project(["myblog"]) == 0

    migrations_dir = tmp_path / "myblog" / "database" / "migrations"
    assert migrations_dir.is_dir()
    files = sorted(p.name for p in migrations_dir.glob("*.py"))
    # Each filename ends with the feature name — check that every
    # expected table-creating migration was copied.
    expected_suffixes = {
        "_create_users.py",
        "_create_password_resets.py",
        "_create_sessions.py",
        "_create_api_tokens.py",
        "_create_roles_and_permissions.py",
        "_create_cache.py",
        "_create_jobs.py",
        "_create_notifications.py",
    }
    for suffix in expected_suffixes:
        assert any(f.endswith(suffix) for f in files), (
            f"missing migration ending in {suffix}; got {files}"
        )


def test_scaffold_migrations_parse_and_chain_correctly(tmp_path: Path) -> None:
    """Generated migrations parse as Python and form a linear alembic chain."""
    import ast
    import re

    os.chdir(tmp_path)
    assert new_project(["myblog"]) == 0

    migrations_dir = tmp_path / "myblog" / "database" / "migrations"
    revisions: dict[str, str | None] = {}
    for path in migrations_dir.glob("*.py"):
        source = path.read_text("utf-8")
        ast.parse(source)  # must be valid Python
        rev_match = re.search(r'revision:\s*str\s*=\s*"([^"]+)"', source)
        down_match = re.search(
            r'down_revision:\s*str\s*\|\s*None\s*=\s*(None|"([^"]+)")',
            source,
        )
        assert rev_match is not None, f"no revision= in {path.name}"
        assert down_match is not None, f"no down_revision= in {path.name}"
        down = down_match.group(2) if down_match.group(2) else None
        revisions[rev_match.group(1)] = down

    # Exactly one root (down_revision=None) and the chain covers every rev.
    roots = [r for r, d in revisions.items() if d is None]
    assert len(roots) == 1, f"expected single root revision, got {roots}"
    # Walk forward from the root and ensure we reach every revision.
    reachable: set[str] = set()
    current: str | None = roots[0]
    while current is not None:
        reachable.add(current)
        next_rev = None
        for rev, down in revisions.items():
            if down == current and rev not in reachable:
                next_rev = rev
                break
        current = next_rev
    assert reachable == set(revisions.keys()), (
        f"revisions not reachable from root: {set(revisions.keys()) - reachable}"
    )
