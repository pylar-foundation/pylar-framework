"""Behavioural tests for :mod:`pylar.console.input`."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from pylar.console.exceptions import ArgumentParseError, CommandDefinitionError
from pylar.console.input import build_parser, parse_args


@dataclass(frozen=True)
class _MakeModelInput:
    model_name: str
    table: str | None = None
    force: bool = False


@dataclass(frozen=True)
class _ServeInput:
    host: str = "127.0.0.1"
    port: int = 8000
    reload: bool = False


@dataclass(frozen=True)
class _DebugInput:
    quiet: bool = True  # default True → exposes --no-quiet


@dataclass(frozen=True)
class _DocumentedInput:
    name: str = field(metadata={"help": "Project name"})


def _parse(input_cls: type, argv: list[str]) -> object:
    parser = build_parser(input_cls, prog="test", description="")
    return parse_args(input_cls, parser, argv)


def test_required_positional_argument() -> None:
    result = _parse(_MakeModelInput, ["User"])
    assert result == _MakeModelInput(model_name="User")


def test_optional_value_with_long_flag() -> None:
    result = _parse(_MakeModelInput, ["User", "--table", "users"])
    assert result == _MakeModelInput(model_name="User", table="users")


def test_kebab_case_flag_for_underscore_field() -> None:
    @dataclass(frozen=True)
    class _Input:
        first_name: str = "anon"

    result = _parse(_Input, ["--first-name", "alice"])
    assert result == _Input(first_name="alice")


def test_bool_flag_default_false_uses_positive_flag() -> None:
    result = _parse(_MakeModelInput, ["User", "--force"])
    assert result == _MakeModelInput(model_name="User", force=True)


def test_bool_flag_default_true_uses_negative_flag() -> None:
    on = _parse(_DebugInput, [])
    assert on == _DebugInput(quiet=True)
    off = _parse(_DebugInput, ["--no-quiet"])
    assert off == _DebugInput(quiet=False)


def test_int_default_is_parsed_from_string() -> None:
    result = _parse(_ServeInput, ["--port", "9090"])
    assert result == _ServeInput(host="127.0.0.1", port=9090, reload=False)


def test_missing_required_positional_raises_argument_error() -> None:
    with pytest.raises(ArgumentParseError):
        _parse(_MakeModelInput, [])


def test_unknown_flag_raises_argument_error() -> None:
    with pytest.raises(ArgumentParseError):
        _parse(_MakeModelInput, ["User", "--unknown"])


def test_field_metadata_help_is_threaded_into_argparse() -> None:
    parser = build_parser(_DocumentedInput, prog="test", description="")
    formatted = parser.format_help()
    assert "Project name" in formatted


def test_non_dataclass_input_rejected() -> None:
    class NotADataclass:
        pass

    with pytest.raises(CommandDefinitionError, match="dataclass"):
        build_parser(NotADataclass, prog="test", description="")


def test_unsupported_union_rejected() -> None:
    @dataclass(frozen=True)
    class _Input:
        value: str | int = "x"

    with pytest.raises(CommandDefinitionError, match="union"):
        build_parser(_Input, prog="test", description="")
