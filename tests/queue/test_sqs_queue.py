"""Tests for the SQS queue driver with an in-process client mock.

Mirrors the S3 approach: instead of moto (which has rough edges
with aioboto3 version combos) we inject a minimal fake async SQS
client that implements only the SDK calls the driver actually uses.
That exercises the driver logic — envelope building, receipt
tracking, DLQ routing, pruning — without any network I/O.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

pytest.importorskip("aioboto3")

from pylar.queue.drivers.sqs import (
    FailedPoolUnavailableError,
    SQSQueue,
)
from pylar.queue.record import JobRecord

# ----------------------------------------------------------- fake client


class _FakeSQSClient:
    """Minimal stand-in for aioboto3 SQS client.

    Tracks messages per queue URL with monotonically increasing
    receipt handles. ``purge_queue`` and ``delete_message`` behave
    enough like the real SDK for the driver to exercise.
    """

    def __init__(self) -> None:
        self.queues: dict[str, list[dict[str, Any]]] = {}
        self._next_handle = 1

    async def send_message(
        self,
        *,
        QueueUrl: str,
        MessageBody: str,
        DelaySeconds: int | None = None,
    ) -> dict[str, Any]:
        queue = self.queues.setdefault(QueueUrl, [])
        handle = f"rh-{self._next_handle}"
        self._next_handle += 1
        queue.append({"Body": MessageBody, "ReceiptHandle": handle})
        return {"MessageId": handle}

    async def receive_message(
        self,
        *,
        QueueUrl: str,
        MaxNumberOfMessages: int = 1,
        WaitTimeSeconds: int = 0,
        VisibilityTimeout: int = 60,
    ) -> dict[str, Any]:
        queue = self.queues.get(QueueUrl, [])
        if not queue:
            return {"Messages": []}
        taken = queue[:MaxNumberOfMessages]
        # Simulate visibility timeout by removing for the duration of
        # the test — good enough since our tests don't wait for it
        # to expire.
        self.queues[QueueUrl] = queue[MaxNumberOfMessages:]
        return {"Messages": taken}

    async def delete_message(
        self, *, QueueUrl: str, ReceiptHandle: str,
    ) -> dict[str, Any]:
        # Already removed by receive_message in this fake, nothing to do.
        return {}

    async def purge_queue(self, *, QueueUrl: str) -> dict[str, Any]:
        self.queues[QueueUrl] = []
        return {}

    async def get_queue_attributes(
        self, *, QueueUrl: str, AttributeNames: list[str],
    ) -> dict[str, Any]:
        size = len(self.queues.get(QueueUrl, []))
        return {"Attributes": {"ApproximateNumberOfMessages": str(size)}}


@asynccontextmanager
async def _client_cm(client: _FakeSQSClient) -> AsyncIterator[_FakeSQSClient]:
    yield client


@pytest.fixture
def fake_client() -> _FakeSQSClient:
    return _FakeSQSClient()


@pytest.fixture
def queue_with_dlq(fake_client: _FakeSQSClient) -> SQSQueue:
    q = SQSQueue(
        queue_url="https://sqs/primary",
        dlq_url="https://sqs/dlq",
    )
    q._client = lambda: _client_cm(fake_client)  # type: ignore[assignment]
    return q


@pytest.fixture
def queue_no_dlq(fake_client: _FakeSQSClient) -> SQSQueue:
    q = SQSQueue(queue_url="https://sqs/primary")
    q._client = lambda: _client_cm(fake_client)  # type: ignore[assignment]
    return q


def _record(rid: str = "1", queue_name: str = "default") -> JobRecord:
    return JobRecord(
        id=rid,
        job_class="tests.jobs:Dummy",
        payload_json="{}",
        queue=queue_name,
    )


# ----------------------------------------------------------- push / pop


async def test_push_then_pop_round_trip(queue_with_dlq: SQSQueue) -> None:
    rec = _record("abc")
    await queue_with_dlq.push(rec)
    popped = await queue_with_dlq.pop(timeout=0)
    assert popped is not None
    assert popped.id == "abc"


async def test_pop_returns_none_on_empty_queue(queue_with_dlq: SQSQueue) -> None:
    assert await queue_with_dlq.pop(timeout=0) is None


async def test_size_reflects_pending_messages(
    queue_with_dlq: SQSQueue, fake_client: _FakeSQSClient,
) -> None:
    assert await queue_with_dlq.size() == 0
    await queue_with_dlq.push(_record("1"))
    await queue_with_dlq.push(_record("2"))
    assert await queue_with_dlq.size() == 2


# ----------------------------------------------------------- ack / fail


async def test_ack_removes_receipt(queue_with_dlq: SQSQueue) -> None:
    await queue_with_dlq.push(_record("1"))
    popped = await queue_with_dlq.pop(timeout=0)
    assert popped is not None
    await queue_with_dlq.ack(popped)
    # After ack the receipt dict should be empty.
    assert queue_with_dlq._receipts == {}


async def test_fail_routes_to_dlq(
    queue_with_dlq: SQSQueue, fake_client: _FakeSQSClient,
) -> None:
    await queue_with_dlq.push(_record("1"))
    popped = await queue_with_dlq.pop(timeout=0)
    assert popped is not None
    await queue_with_dlq.fail(popped, "boom")
    # DLQ now holds the failed record with its error.
    dlq_msgs = fake_client.queues.get("https://sqs/dlq", [])
    assert len(dlq_msgs) == 1
    envelope = json.loads(dlq_msgs[0]["Body"])
    assert envelope["error"] == "boom"
    restored = JobRecord.model_validate_json(envelope["record"])
    assert restored.id == "1"


async def test_fail_without_dlq_just_deletes(
    queue_no_dlq: SQSQueue, fake_client: _FakeSQSClient,
) -> None:
    await queue_no_dlq.push(_record("1"))
    popped = await queue_no_dlq.pop(timeout=0)
    assert popped is not None
    await queue_no_dlq.fail(popped, "boom")
    # No DLQ created — the message is simply gone.
    assert "https://sqs/dlq" not in fake_client.queues


# --------------------------------------------------- failed pool requires DLQ


async def test_failed_pool_ops_raise_without_dlq(
    queue_no_dlq: SQSQueue,
) -> None:
    with pytest.raises(FailedPoolUnavailableError):
        await queue_no_dlq.failed_records()
    with pytest.raises(FailedPoolUnavailableError):
        await queue_no_dlq.retry_failed()
    with pytest.raises(FailedPoolUnavailableError):
        await queue_no_dlq.forget_failed("x")
    with pytest.raises(FailedPoolUnavailableError):
        await queue_no_dlq.flush_failed()


async def test_retry_failed_moves_record_back_to_primary(
    queue_with_dlq: SQSQueue, fake_client: _FakeSQSClient,
) -> None:
    await queue_with_dlq.push(_record("1"))
    popped = await queue_with_dlq.pop(timeout=0)
    assert popped is not None
    await queue_with_dlq.fail(popped, "err")
    assert len(fake_client.queues["https://sqs/dlq"]) == 1

    moved = await queue_with_dlq.retry_failed()
    assert moved == 1
    # DLQ drained, primary re-populated.
    assert fake_client.queues["https://sqs/dlq"] == []
    assert len(fake_client.queues["https://sqs/primary"]) == 1


async def test_prune_failed_drops_only_old_records(
    queue_with_dlq: SQSQueue, fake_client: _FakeSQSClient,
) -> None:
    old = JobRecord(
        id="old", job_class="x:X", payload_json="{}",
        queued_at=datetime.now(UTC) - timedelta(days=30),
    )
    fresh = JobRecord(id="new", job_class="x:X", payload_json="{}")
    # Seed the DLQ directly with the envelope format.
    for r in (old, fresh):
        fake_client.queues.setdefault("https://sqs/dlq", []).append({
            "Body": json.dumps({"record": r.model_dump_json(), "error": ""}),
            "ReceiptHandle": f"rh-{r.id}",
        })

    cutoff = datetime.now(UTC) - timedelta(days=7)
    removed = await queue_with_dlq.prune_failed(cutoff)
    assert removed == 1
