"""Behavioural tests for :class:`pylar.console.ConsoleKernel`."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from pylar.console import COMMANDS_TAG, Command, ConsoleKernel
from pylar.foundation import (
    AppConfig,
    Application,
    Container,
    ServiceProvider,
)

# --------------------------------------------------------------------- fixtures


class CallSink:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []


_SINK = CallSink()


@dataclass(frozen=True)
class GreetInput:
    target: str
    shout: bool = False


class GreetCommand(Command[GreetInput]):
    name = "greet"
    description = "Greet someone"
    input_type = GreetInput

    def __init__(self, sink: CallSink) -> None:
        self.sink = sink

    async def handle(self, input: GreetInput) -> int:
        message = f"hello {input.target}"
        if input.shout:
            message = message.upper()
        self.sink.calls.append(("greet", message))
        return 0


@dataclass(frozen=True)
class _NoArgsInput:
    pass


class FailingCommand(Command[_NoArgsInput]):
    name = "fail"
    description = "Always exits with status 7"
    input_type = _NoArgsInput

    async def handle(self, input: _NoArgsInput) -> int:
        return 7


class _ConsoleProvider(ServiceProvider):
    def register(self, container: Container) -> None:
        container.instance(CallSink, _SINK)
        container.tag([GreetCommand, FailingCommand], COMMANDS_TAG)


def _make_app() -> Application:
    return Application(
        base_path=Path("/tmp/pylar-console-test"),
        config=AppConfig(name="console-test", debug=True, providers=(_ConsoleProvider,)),
    )


@pytest.fixture(autouse=True)
def _reset_sink() -> None:
    _SINK.calls.clear()


# ------------------------------------------------------------------------ tests


async def test_runs_command_with_positional_argument() -> None:
    app = _make_app()
    code = await ConsoleKernel(app, ["greet", "world"]).handle()
    assert code == 0
    assert _SINK.calls == [("greet", "hello world")]


async def test_runs_command_with_flag() -> None:
    app = _make_app()
    code = await ConsoleKernel(app, ["greet", "world", "--shout"]).handle()
    assert code == 0
    assert _SINK.calls == [("greet", "HELLO WORLD")]


async def test_command_exit_code_is_propagated() -> None:
    app = _make_app()
    code = await ConsoleKernel(app, ["fail"]).handle()
    assert code == 7


async def test_unknown_command_returns_non_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    app = _make_app()
    code = await ConsoleKernel(app, ["does-not-exist"]).handle()
    assert code == 1
    captured = capsys.readouterr()
    assert "Unknown command" in captured.err


async def test_argument_error_returns_dedicated_status(
    capsys: pytest.CaptureFixture[str],
) -> None:
    app = _make_app()
    code = await ConsoleKernel(app, ["greet"]).handle()  # missing positional
    assert code == 2
    captured = capsys.readouterr()
    assert "Argument error" in captured.err


async def test_empty_argv_runs_list_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    app = _make_app()
    code = await ConsoleKernel(app, []).handle()
    assert code == 0
    captured = capsys.readouterr()
    assert "greet" in captured.out
    assert "fail" in captured.out
    assert "list" in captured.out  # built-in command is registered


async def test_list_command_lists_user_and_builtin_commands(
    capsys: pytest.CaptureFixture[str],
) -> None:
    app = _make_app()
    code = await ConsoleKernel(app, ["list"]).handle()
    assert code == 0
    out = capsys.readouterr().out
    # alphabetical order: fail, greet, list
    fail_at = out.index("fail")
    greet_at = out.index("greet")
    list_at = out.index("list")
    assert fail_at < greet_at < list_at
