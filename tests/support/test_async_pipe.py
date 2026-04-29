"""Tests for pipe() and sequence() async chaining helpers."""

from __future__ import annotations

from pylar.support import pipe, sequence


async def _async_double(x: int) -> int:
    return x * 2


async def _async_add(x: int, y: int) -> int:
    return x + y


async def test_pipe_with_coroutine_seed() -> None:
    result = await pipe(_async_double(3))
    assert result == 6


async def test_pipe_with_value_seed() -> None:
    result = await pipe(10)
    assert result == 10


async def test_pipe_then_with_async_fn() -> None:
    result = await pipe(_async_double(2)).then(_async_double)
    assert result == 8  # 2 * 2 * 2


async def test_pipe_then_with_sync_fn() -> None:
    result = await pipe(_async_double(5)).then(lambda n: n + 1)
    assert result == 11  # 5*2 + 1


async def test_pipe_long_chain() -> None:
    result = await (
        pipe(1)
        .then(lambda n: n + 1)
        .then(_async_double)
        .then(lambda n: n * 10)
    )
    assert result == 40  # ((1+1)*2)*10


async def test_pipe_tap_passes_value_through() -> None:
    captured: list[int] = []
    result = await (
        pipe(5)
        .tap(lambda n: captured.append(n))
        .then(_async_double)
    )
    assert result == 10
    assert captured == [5]


async def test_pipe_tap_with_async_side_effect() -> None:
    captured: list[int] = []

    async def _record(n: int) -> None:
        captured.append(n)

    result = await pipe(_async_double(3)).tap(_record).then(lambda n: n + 1)
    assert result == 7
    assert captured == [6]


async def test_sequence_returns_last_result() -> None:
    result = await sequence(
        _async_double(1),
        _async_double(2),
        _async_double(3),
    )
    assert result == 6


async def test_sequence_with_mixed_values() -> None:
    result = await sequence(
        _async_double(1),
        42,  # plain value
        _async_double(5),
    )
    assert result == 10


async def test_sequence_empty_returns_none() -> None:
    result = await sequence()
    assert result is None


async def test_pipe_short_circuit_on_exception() -> None:
    """Exceptions in the chain propagate without running subsequent steps."""
    import pytest

    calls: list[str] = []

    def _raise(_: int) -> int:
        calls.append("raise")
        raise ValueError("boom")

    def _should_not_run(_: int) -> int:
        calls.append("after")
        return 0

    with pytest.raises(ValueError, match="boom"):
        await pipe(1).then(_raise).then(_should_not_run)
    assert calls == ["raise"]
