"""Discover and load user config modules from a directory."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from pydantic import BaseModel

from pylar.config.exceptions import ConfigLoadError
from pylar.foundation.container import Container


class ConfigLoader:
    """Load every ``*.py`` config module from a directory.

    Each module must export a single attribute named ``config`` that is an
    instance of any pydantic ``BaseModel`` — :class:`BaseConfig` is the
    recommended base because it pre-fills the strict defaults pylar prefers,
    but the loader also accepts the framework's own bootstrap models such
    as :class:`AppConfig` so that ``config/app.py`` can sit next to the
    domain configs without tripping a type check.

    The loader binds each discovered instance into the container under its
    concrete type, so providers can request it via :meth:`Container.make`.
    Files starting with ``_`` are skipped (e.g. ``__init__.py``); the
    iteration order is sorted by filename so registration is deterministic.

    The loader does not touch ``sys.path``: callers are responsible for
    making sure the project root is importable so that config modules can
    ``from app...`` if needed. The pylar CLI sets this up automatically
    before constructing the :class:`Application`.
    """

    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path

    def discover(self) -> list[BaseModel]:
        """Return every pydantic model instance found under ``config_path``."""
        if not self.config_path.is_dir():
            return []

        configs: list[BaseModel] = []
        for path in sorted(self.config_path.glob("*.py")):
            if path.name.startswith("_"):
                continue
            module = self._load_module(path)
            cfg = self._try_extract_config(module)
            if cfg is not None:
                configs.append(cfg)
        return configs

    def bind_into(self, container: Container) -> list[BaseModel]:
        """Discover all configs and register each one as a singleton instance."""
        configs = self.discover()
        for cfg in configs:
            container.instance(type(cfg), cfg)
        return configs

    # ----------------------------------------------------------------- internals

    def _load_module(self, path: Path) -> ModuleType:
        spec = importlib.util.spec_from_file_location(f"_pylar_config_{path.stem}", path)
        if spec is None or spec.loader is None:
            raise ConfigLoadError(f"Cannot create import spec for {path}")
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            raise ConfigLoadError(f"Failed to import config module {path.name}: {exc}") from exc
        return module

    def _try_extract_config(self, module: ModuleType) -> BaseModel | None:
        """Return the ``config`` attribute if it is a pydantic BaseModel.

        Files in ``config/`` that don't export a ``config: BaseModel``
        are silently skipped — they may contain helper values consumed
        by providers directly (e.g. ``config/queue.py`` exporting a
        ``QueuesConfig`` dataclass that ``AppServiceProvider`` binds
        by hand).
        """
        cfg = getattr(module, "config", None)
        if cfg is None:
            return None
        if not isinstance(cfg, BaseModel):
            return None
        return cfg
