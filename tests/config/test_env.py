"""Behavioural tests for :mod:`pylar.config.env`."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pylar.config import EnvError, env, load_dotenv


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("PYLAR_TEST_"):
            monkeypatch.delenv(key, raising=False)


def test_str_returns_value_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYLAR_TEST_NAME", "alice")
    assert env.str("PYLAR_TEST_NAME") == "alice"


def test_str_returns_default_when_missing() -> None:
    assert env.str("PYLAR_TEST_NAME", "fallback") == "fallback"


def test_str_raises_when_missing_and_no_default() -> None:
    with pytest.raises(EnvError, match="not set"):
        env.str("PYLAR_TEST_NAME")


def test_int_parses_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYLAR_TEST_PORT", "5432")
    assert env.int("PYLAR_TEST_PORT") == 5432


def test_int_returns_default_when_missing() -> None:
    assert env.int("PYLAR_TEST_PORT", 8080) == 8080


def test_int_raises_when_unparsable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYLAR_TEST_PORT", "abc")
    with pytest.raises(EnvError, match="not a valid int"):
        env.int("PYLAR_TEST_PORT")


@pytest.mark.parametrize("raw,expected", [
    ("1", True), ("true", True), ("YES", True), ("on", True),
    ("0", False), ("false", False), ("NO", False), ("off", False), ("", False),
])
def test_bool_recognised_values(
    monkeypatch: pytest.MonkeyPatch, raw: str, expected: bool
) -> None:
    monkeypatch.setenv("PYLAR_TEST_FLAG", raw)
    assert env.bool("PYLAR_TEST_FLAG") is expected


def test_bool_default(monkeypatch: pytest.MonkeyPatch) -> None:
    assert env.bool("PYLAR_TEST_FLAG", False) is False
    assert env.bool("PYLAR_TEST_FLAG", True) is True


def test_bool_raises_on_garbage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYLAR_TEST_FLAG", "maybe")
    with pytest.raises(EnvError, match="not a valid bool"):
        env.bool("PYLAR_TEST_FLAG")


def test_load_dotenv_populates_environ(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "# comment\n"
        "PYLAR_TEST_NAME=alice\n"
        'PYLAR_TEST_QUOTED="hello world"\n'
        "\n"
        "PYLAR_TEST_PORT=5432\n",
        encoding="utf-8",
    )

    loaded = load_dotenv(dotenv)
    assert loaded == {
        "PYLAR_TEST_NAME": "alice",
        "PYLAR_TEST_QUOTED": "hello world",
        "PYLAR_TEST_PORT": "5432",
    }
    assert os.environ["PYLAR_TEST_NAME"] == "alice"
    assert os.environ["PYLAR_TEST_QUOTED"] == "hello world"


def test_load_dotenv_does_not_override_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PYLAR_TEST_NAME", "bob")
    dotenv = tmp_path / ".env"
    dotenv.write_text("PYLAR_TEST_NAME=alice\n", encoding="utf-8")

    load_dotenv(dotenv)
    assert os.environ["PYLAR_TEST_NAME"] == "bob"


def test_load_dotenv_override_true(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PYLAR_TEST_NAME", "bob")
    dotenv = tmp_path / ".env"
    dotenv.write_text("PYLAR_TEST_NAME=alice\n", encoding="utf-8")

    load_dotenv(dotenv, override=True)
    assert os.environ["PYLAR_TEST_NAME"] == "alice"


def test_load_dotenv_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_dotenv(tmp_path / "nope.env") == {}


def test_load_dotenv_malformed_line_raises(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text("BROKEN_LINE_NO_EQUALS\n", encoding="utf-8")
    with pytest.raises(EnvError, match="Malformed"):
        load_dotenv(dotenv)
