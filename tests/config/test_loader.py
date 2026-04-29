"""Behavioural tests for :class:`pylar.config.ConfigLoader`."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from pylar.config import BaseConfig, ConfigLoader, ConfigLoadError
from pylar.foundation import Container


class _DatabaseConfig(BaseConfig):
    host: str
    port: int = 5432


class _MailConfig(BaseConfig):
    dsn: str


def _write(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


def test_discover_returns_empty_when_directory_missing(tmp_path: Path) -> None:
    loader = ConfigLoader(tmp_path / "does-not-exist")
    assert loader.discover() == []


def test_discover_loads_every_module(tmp_path: Path) -> None:
    _write(
        tmp_path / "database.py",
        "from tests.config.test_loader import _DatabaseConfig\n"
        "config = _DatabaseConfig(host='localhost', port=5432)\n",
    )
    _write(
        tmp_path / "mail.py",
        "from tests.config.test_loader import _MailConfig\n"
        "config = _MailConfig(dsn='smtp://localhost')\n",
    )

    configs = ConfigLoader(tmp_path).discover()
    assert len(configs) == 2
    types = {type(c) for c in configs}
    assert types == {_DatabaseConfig, _MailConfig}


def test_discover_skips_underscore_files(tmp_path: Path) -> None:
    _write(tmp_path / "__init__.py", "")
    _write(
        tmp_path / "_private.py",
        "from tests.config.test_loader import _DatabaseConfig\n"
        "config = _DatabaseConfig(host='x')\n",
    )
    assert ConfigLoader(tmp_path).discover() == []


def test_missing_config_attribute_skipped(tmp_path: Path) -> None:
    _write(tmp_path / "broken.py", "x = 1\n")
    assert ConfigLoader(tmp_path).discover() == []


def test_non_pydantic_config_skipped(tmp_path: Path) -> None:
    _write(tmp_path / "wrong.py", "config = {'host': 'x'}\n")
    assert ConfigLoader(tmp_path).discover() == []


def test_loader_accepts_plain_pydantic_basemodel(tmp_path: Path) -> None:
    """A non-BaseConfig pydantic model should still be picked up.

    AppConfig is the bootstrap example: it lives in ``config/app.py``
    and is a plain BaseModel rather than a BaseConfig subclass.
    """
    _write(
        tmp_path / "plain.py",
        "from pydantic import BaseModel\n"
        "class Plain(BaseModel):\n"
        "    name: str\n"
        "config = Plain(name='ok')\n",
    )
    configs = ConfigLoader(tmp_path).discover()
    assert len(configs) == 1
    assert configs[0].name == "ok"  # type: ignore[attr-defined]


def test_import_failure_propagates_as_load_error(tmp_path: Path) -> None:
    _write(tmp_path / "boom.py", "raise RuntimeError('nope')\n")
    with pytest.raises(ConfigLoadError, match="Failed to import"):
        ConfigLoader(tmp_path).discover()


def test_bind_into_registers_each_config_by_type(tmp_path: Path) -> None:
    _write(
        tmp_path / "database.py",
        "from tests.config.test_loader import _DatabaseConfig\n"
        "config = _DatabaseConfig(host='db.local', port=6543)\n",
    )
    container = Container()
    loader = ConfigLoader(tmp_path)
    loader.bind_into(container)

    cfg = container.make(_DatabaseConfig)
    assert cfg.host == "db.local"
    assert cfg.port == 6543


def test_baseconfig_is_frozen() -> None:
    cfg = _DatabaseConfig(host="x")
    with pytest.raises(ValidationError):
        cfg.host = "y"


def test_baseconfig_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        _DatabaseConfig(host="x", unknown_field="y")  # type: ignore[call-arg]
