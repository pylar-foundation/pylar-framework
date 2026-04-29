"""Tests for scheduling hooks (before/after/success/failure) and conditions (when/skip)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from pylar.foundation.container import Container
from pylar.scheduling import Schedule


async def _noop() -> None:
    pass


async def _fail() -> None:
    raise RuntimeError("boom")


@pytest.fixture
def container() -> Container:
    return Container()


async def test_before_and_after_hooks_fire(container: Container) -> None:
    calls: list[str] = []
    schedule = Schedule()
    schedule.call(_noop).cron("* * * * *").before(
        lambda: calls.append("before")
    ).after(lambda: calls.append("after"))

    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    await schedule.run_due(container, now=now)

    assert calls == ["before", "after"]


async def test_success_hook_fires_on_success(container: Container) -> None:
    calls: list[str] = []
    schedule = Schedule()
    schedule.call(_noop).cron("* * * * *").on_success(
        lambda: calls.append("ok")
    ).on_failure(lambda _: calls.append("fail"))

    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    await schedule.run_due(container, now=now)

    assert calls == ["ok"]


async def test_failure_hook_fires_on_exception(container: Container) -> None:
    calls: list[object] = []
    schedule = Schedule()
    schedule.call(_fail).cron("* * * * *").on_success(
        lambda: calls.append("ok")
    ).on_failure(lambda exc: calls.append(str(exc)))

    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    with pytest.raises(RuntimeError, match="boom"):
        await schedule.run_due(container, now=now)

    assert calls == ["boom"]


async def test_when_condition_blocks_execution(container: Container) -> None:
    ran = []
    schedule = Schedule()
    schedule.call(
        lambda: _record(ran)
    ).cron("* * * * *").when(lambda: False)

    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    count = await schedule.run_due(container, now=now)

    assert count == 0
    assert ran == []


async def test_when_condition_allows_when_true(container: Container) -> None:
    ran = []
    schedule = Schedule()
    schedule.call(
        lambda: _record(ran)
    ).cron("* * * * *").when(lambda: True)

    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    count = await schedule.run_due(container, now=now)

    assert count == 1
    assert ran == ["ran"]


async def test_skip_condition_blocks_execution(container: Container) -> None:
    ran = []
    schedule = Schedule()
    schedule.call(
        lambda: _record(ran)
    ).cron("* * * * *").skip(lambda: True)

    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    count = await schedule.run_due(container, now=now)

    assert count == 0


async def test_multiple_when_all_must_pass(container: Container) -> None:
    ran = []
    schedule = Schedule()
    schedule.call(
        lambda: _record(ran)
    ).cron("* * * * *").when(lambda: True).when(lambda: False)

    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    count = await schedule.run_due(container, now=now)

    assert count == 0


def _record(acc: list[str]) -> object:
    async def _inner() -> None:
        acc.append("ran")

    return _inner()
