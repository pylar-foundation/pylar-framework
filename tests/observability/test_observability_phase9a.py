"""Tests for observability phase 9a (ADR-0008).

Covers:
* JsonFormatter shape — timestamp/level/logger/message, extra fields,
  request-id correlation via ContextVar.
* install_json_logging() resets root handlers and installs the
  formatter.
* AboutCommand output contains the expected sections.
* DoctorCommand exit code + pass/fail reporting per check type.
"""

from __future__ import annotations

import json
import logging
from io import StringIO

import pytest

from pylar.cache import Cache, MemoryCacheStore
from pylar.console.output import Output
from pylar.foundation import AppConfig, Application, Container
from pylar.observability import (
    AboutCommand,
    DoctorCommand,
    JsonFormatter,
    install_json_logging,
)
from pylar.observability.commands import _AboutInput
from pylar.observability.doctor import _DoctorInput

# --------------------------------------------------------- JsonFormatter


def test_json_formatter_emits_well_shaped_record() -> None:
    fmt = JsonFormatter()
    record = logging.LogRecord(
        name="pylar.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    parsed = json.loads(fmt.format(record))
    assert parsed["message"] == "hello world"
    assert parsed["level"] == "INFO"
    assert parsed["logger"] == "pylar.test"
    assert "timestamp" in parsed


def test_json_formatter_carries_request_id_from_contextvar() -> None:
    from pylar.http.middlewares.request_id import _current_request_id

    token = _current_request_id.set("trace-abc")
    try:
        fmt = JsonFormatter()
        record = logging.LogRecord(
            name="pylar.test", level=logging.INFO, pathname="p", lineno=1,
            msg="m", args=None, exc_info=None,
        )
        parsed = json.loads(fmt.format(record))
        assert parsed["request_id"] == "trace-abc"
    finally:
        _current_request_id.reset(token)


def test_json_formatter_surfaces_extras() -> None:
    fmt = JsonFormatter()
    record = logging.LogRecord(
        name="pylar.test", level=logging.WARNING, pathname="p", lineno=1,
        msg="something happened", args=None, exc_info=None,
    )
    record.duration_ms = 47  # type: ignore[attr-defined]
    record.user_id = 42  # type: ignore[attr-defined]
    parsed = json.loads(fmt.format(record))
    assert parsed["duration_ms"] == 47
    assert parsed["user_id"] == 42


def test_install_json_logging_replaces_root_handlers() -> None:
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    try:
        install_json_logging(level="DEBUG")
        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0].formatter, JsonFormatter)
        assert root.level == logging.DEBUG
    finally:
        for h in list(root.handlers):
            root.removeHandler(h)
        for h in saved_handlers:
            root.addHandler(h)
        root.setLevel(saved_level)


# -------------------------------------------------------- AboutCommand


@pytest.fixture
def app() -> Application:
    return Application(
        base_path=__import__("pathlib").Path("/tmp/pylar-about-test"),
        config=AppConfig(name="about-test", debug=True, providers=()),
    )


async def test_about_command_prints_application_section(app: Application) -> None:
    buf = StringIO()
    cmd = AboutCommand(app, app.container, Output(buf, colour=False))
    code = await cmd.handle(_AboutInput())
    assert code == 0
    out = buf.getvalue()
    assert "Application" in out
    assert "about-test" in out


async def test_about_command_masks_database_password(app: Application) -> None:
    from pylar.database import DatabaseConfig

    app.container.instance(
        DatabaseConfig,
        DatabaseConfig(url="postgres://bob:supersecret@db:5432/app"),
    )
    buf = StringIO()
    cmd = AboutCommand(app, app.container, Output(buf, colour=False))
    await cmd.handle(_AboutInput())
    out = buf.getvalue()
    assert "Database" in out
    assert "supersecret" not in out
    assert "bob:***" in out


# -------------------------------------------------------- DoctorCommand


async def test_doctor_passes_on_healthy_cache() -> None:
    container = Container()
    container.instance(Cache, Cache(MemoryCacheStore()))
    buf = StringIO()
    cmd = DoctorCommand(container, Output(buf, colour=False))
    code = await cmd.handle(_DoctorInput())
    assert code == 0
    out = buf.getvalue()
    assert "Cache" in out
    # One pass mark for cache; every other probe skips cleanly.
    assert "round-trip" in out


async def test_doctor_fails_when_probe_raises() -> None:
    class BrokenStore:
        async def put(self, *a: object, **kw: object) -> None:
            raise RuntimeError("cache backend offline")

        async def get(self, *a: object, **kw: object) -> object:
            raise RuntimeError("cache backend offline")

        async def forget(self, *a: object, **kw: object) -> None:
            pass

    container = Container()
    container.instance(Cache, Cache(BrokenStore()))  # type: ignore[arg-type]

    buf = StringIO()
    cmd = DoctorCommand(container, Output(buf, colour=False))
    code = await cmd.handle(_DoctorInput())
    assert code == 1
    out = buf.getvalue()
    assert "failed" in out.lower()
