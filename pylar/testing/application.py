"""Convenience constructors for test :class:`Application` instances."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from pylar.foundation import AppConfig, Application, ServiceProvider


def create_test_app(
    *,
    providers: Sequence[type[ServiceProvider]] = (),
    name: str = "pylar-test",
    debug: bool = True,
    base_path: Path | None = None,
) -> Application:
    """Build an :class:`Application` for tests with sensible defaults.

    The default ``base_path`` points at a non-existent directory under
    ``/tmp`` so that :class:`ConfigLoader` finds nothing and the test
    environment is fully controlled by the ``providers`` argument. Tests
    that need a real ``base_path`` (templates, language files,
    migrations) should pass one explicitly.
    """
    return Application(
        base_path=base_path or Path("/tmp/pylar-test-no-config"),
        config=AppConfig(name=name, debug=debug, providers=tuple(providers)),
    )
