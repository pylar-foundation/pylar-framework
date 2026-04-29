"""Tests for the SQLAlchemy-backed DatabaseQueue driver."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from pylar.queue import DatabaseQueue, JobRecord


@pytest.fixture
async def queue() -> AsyncIterator[DatabaseQueue]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    q = DatabaseQueue(engine, poll_interval=0.01)
    await q.bootstrap()
    try:
        yield q
    finally:
        await engine.dispose()


def _make_record(
    *, available_at: datetime | None = None, attempts: int = 0
) -> JobRecord:
    now = datetime.now(UTC)
    return JobRecord(
        id=str(uuid4()),
        job_class="tests.fake.Job",
        payload_json="{}",
        attempts=attempts,
        queued_at=now,
        available_at=available_at if available_at is not None else now,
    )


async def test_push_and_pop_round_trip(queue: DatabaseQueue) -> None:
    rec = _make_record()
    await queue.push(rec)

    popped = await queue.pop(timeout=0.1)
    assert popped is not None
    assert popped.id == rec.id


async def test_pop_returns_none_on_empty_queue(queue: DatabaseQueue) -> None:
    assert await queue.pop(timeout=0.05) is None


async def test_pop_respects_available_at(queue: DatabaseQueue) -> None:
    future = datetime.now(UTC) + timedelta(seconds=10)
    await queue.push(_make_record(available_at=future))
    assert await queue.pop(timeout=0.05) is None


async def test_ack_removes_job(queue: DatabaseQueue) -> None:
    rec = _make_record()
    await queue.push(rec)
    popped = await queue.pop(timeout=0.1)
    assert popped is not None
    await queue.ack(popped)
    # No second job to pop.
    assert await queue.pop(timeout=0.05) is None


async def test_fail_moves_to_failed_pool(queue: DatabaseQueue) -> None:
    rec = _make_record()
    await queue.push(rec)
    popped = await queue.pop(timeout=0.1)
    assert popped is not None
    await queue.fail(popped, "boom")

    failed = await queue.failed_records()
    assert len(failed) == 1
    assert failed[0].record.id == rec.id
    assert failed[0].error == "boom"


async def test_retry_failed_all(queue: DatabaseQueue) -> None:
    rec = _make_record()
    await queue.push(rec)
    popped = await queue.pop(timeout=0.1)
    assert popped is not None
    await queue.fail(popped, "transient")

    moved = await queue.retry_failed()
    assert moved == 1
    assert await queue.failed_records() == []

    again = await queue.pop(timeout=0.1)
    assert again is not None
    assert again.id == rec.id


async def test_retry_failed_by_id(queue: DatabaseQueue) -> None:
    a = _make_record()
    b = _make_record()
    await queue.push(a)
    await queue.push(b)
    pa = await queue.pop(timeout=0.1)
    pb = await queue.pop(timeout=0.1)
    assert pa is not None and pb is not None
    await queue.fail(pa, "x")
    await queue.fail(pb, "y")

    moved = await queue.retry_failed(pa.id)
    assert moved == 1
    failed = await queue.failed_records()
    assert {f.record.id for f in failed} == {pb.id}


async def test_push_then_retry_with_bumped_attempts(queue: DatabaseQueue) -> None:
    """Re-pushing the same id should preserve identity and update attempts."""
    rec = _make_record()
    await queue.push(rec)
    popped = await queue.pop(timeout=0.1)
    assert popped is not None

    retry = popped.model_copy(update={"attempts": 1})
    await queue.push(retry)

    again = await queue.pop(timeout=0.1)
    assert again is not None
    assert again.id == rec.id
    assert again.attempts == 1


async def test_two_workers_do_not_double_process(queue: DatabaseQueue) -> None:
    rec = _make_record()
    await queue.push(rec)

    import asyncio

    a, b = await asyncio.gather(
        queue.pop(timeout=0.1), queue.pop(timeout=0.1)
    )
    # Exactly one worker claims the record.
    assert (a is None) ^ (b is None)
