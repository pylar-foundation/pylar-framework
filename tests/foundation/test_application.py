"""Behavioural tests for :class:`pylar.foundation.Application` and ServiceProvider lifecycle."""

from __future__ import annotations

from pathlib import Path

import pytest

from pylar.foundation import (
    AppConfig,
    Application,
    Container,
    Kernel,
    ServiceProvider,
)


class TraceLog:
    def __init__(self) -> None:
        self.events: list[str] = []


# A module-level singleton lets providers communicate without resorting to globals
# inside the framework itself.
_TRACE = TraceLog()


class _ResetTrace:
    """pytest fixture helper — clear the shared trace between tests."""

    def __enter__(self) -> TraceLog:
        _TRACE.events.clear()
        return _TRACE

    def __exit__(self, *_: object) -> None:
        _TRACE.events.clear()


@pytest.fixture
def trace() -> TraceLog:
    _TRACE.events.clear()
    return _TRACE


# --------------------------------------------------------------------- providers


class FirstProvider(ServiceProvider):
    def register(self, container: Container) -> None:
        _TRACE.events.append("first.register")

    async def boot(self, container: Container) -> None:
        _TRACE.events.append("first.boot")

    async def shutdown(self, container: Container) -> None:
        _TRACE.events.append("first.shutdown")


class SecondProvider(ServiceProvider):
    def register(self, container: Container) -> None:
        _TRACE.events.append("second.register")

    async def boot(self, container: Container) -> None:
        _TRACE.events.append("second.boot")

    async def shutdown(self, container: Container) -> None:
        _TRACE.events.append("second.shutdown")


def _make_app(*providers: type[ServiceProvider]) -> Application:
    config = AppConfig(name="test", debug=True, providers=providers)
    return Application(base_path=Path("/tmp/pylar-test"), config=config)


# ------------------------------------------------------------------------ tests


async def test_bootstrap_registers_then_boots_in_order(trace: TraceLog) -> None:
    app = _make_app(FirstProvider, SecondProvider)
    await app.bootstrap()

    assert trace.events == [
        "first.register",
        "second.register",
        "first.boot",
        "second.boot",
    ]
    assert app.is_booted


async def test_bootstrap_is_idempotent(trace: TraceLog) -> None:
    app = _make_app(FirstProvider)
    await app.bootstrap()
    await app.bootstrap()

    assert trace.events.count("first.register") == 1
    assert trace.events.count("first.boot") == 1


async def test_shutdown_runs_in_reverse_order(trace: TraceLog) -> None:
    app = _make_app(FirstProvider, SecondProvider)
    await app.bootstrap()
    trace.events.clear()

    await app.shutdown()
    assert trace.events == ["second.shutdown", "first.shutdown"]
    assert not app.is_booted


async def test_run_invokes_kernel_between_bootstrap_and_shutdown(trace: TraceLog) -> None:
    class _Kernel:
        async def handle(self) -> int:
            _TRACE.events.append("kernel.handle")
            return 42

    app = _make_app(FirstProvider)
    code = await app.run(_Kernel())

    assert code == 42
    assert trace.events == [
        "first.register",
        "first.boot",
        "kernel.handle",
        "first.shutdown",
    ]


async def test_run_shuts_down_even_when_kernel_raises(trace: TraceLog) -> None:
    class _Kernel:
        async def handle(self) -> int:
            raise RuntimeError("boom")

    app = _make_app(FirstProvider)
    with pytest.raises(RuntimeError, match="boom"):
        await app.run(_Kernel())

    assert "first.shutdown" in trace.events


def test_core_bindings_available_immediately(trace: TraceLog) -> None:
    app = _make_app()
    assert app.container.make(Application) is app
    assert app.container.make(Container) is app.container
    assert app.container.make(AppConfig) is app.config


def test_kernel_protocol_is_runtime_checkable() -> None:
    class _Kernel:
        async def handle(self) -> int:
            return 0

    assert isinstance(_Kernel(), Kernel)
