"""Amazon SQS queue driver.

Implements the :class:`pylar.queue.JobQueue` Protocol against SQS. The
mapping to SQS's message model is deliberately thin:

* ``push`` → :code:`send_message` (with ``DelaySeconds`` for records
  whose ``available_at`` is in the future; SQS allows up to 900 s).
* ``pop``  → :code:`receive_message` with long-polling. SQS does not
  support cross-queue prioritised pop, so the driver walks the queues
  tuple left-to-right and returns the first non-empty one.
* ``ack``  → :code:`delete_message` with the stored receipt handle.
* ``fail`` → sends the record body to the configured DLQ (if any) and
  then deletes the original message so SQS does not redeliver it.

Operator surface (``failed_records``, ``retry_failed``,
``forget_failed``, ``flush_failed``, ``prune_failed``) requires a DLQ
URL — SQS has no native "failed pool" API. When no DLQ is configured
these calls raise :class:`FailedPoolUnavailableError` so misuse
surfaces immediately rather than silently dropping data.

Install via ``pylar[queue-sqs]`` which pulls in ``aioboto3``.

Usage::

    from pylar.queue.drivers.sqs import SQSQueue

    queue = SQSQueue(
        queue_url="https://sqs.eu-central-1.amazonaws.com/123/pylar",
        dlq_url="https://sqs.eu-central-1.amazonaws.com/123/pylar-dlq",
        region="eu-central-1",
    )
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

try:
    import aioboto3
except ImportError:  # pragma: no cover
    raise ImportError(
        "SQSQueue requires the 'aioboto3' package. "
        "Install it with: pip install 'pylar[queue-sqs]'"
    ) from None

from pylar.queue.exceptions import QueueError
from pylar.queue.queue import FailedJob
from pylar.queue.record import JobRecord


class FailedPoolUnavailableError(QueueError):
    """Raised when a failed-pool operation is called without a DLQ."""


class SQSQueue:
    """A :class:`JobQueue` backed by Amazon SQS.

    *queue_url* is the primary work queue. *dlq_url*, when provided,
    receives records the worker could not process so operators can
    inspect, re-queue, or purge them. Without a DLQ the driver raises
    on every failed-pool call — this is by design so the operator
    chooses DLQ behaviour explicitly.

    *visibility_timeout* is the SQS reservation window — how long a
    popped message stays hidden from other consumers while the worker
    processes it. Should comfortably exceed the longest expected job
    duration; SQS redelivers the message if the worker dies.

    ``JobRecord`` is frozen, so the driver keeps an in-process
    ``{record.id: receipt_handle}`` map populated on ``pop`` and
    drained on ``ack`` / ``fail``. If a worker crashes after ``pop``
    but before ``ack``, SQS automatically redelivers the message once
    the visibility timeout elapses.
    """

    def __init__(
        self,
        *,
        queue_url: str,
        dlq_url: str | None = None,
        region: str = "",
        visibility_timeout: int = 60,
        max_delay_seconds: int = 900,
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
    ) -> None:
        self._queue_url = queue_url
        self._dlq_url = dlq_url
        self._visibility_timeout = visibility_timeout
        self._max_delay_seconds = max_delay_seconds

        session_kwargs: dict[str, Any] = {}
        if region:
            session_kwargs["region_name"] = region
        if aws_access_key_id:
            session_kwargs["aws_access_key_id"] = aws_access_key_id
        if aws_secret_access_key:
            session_kwargs["aws_secret_access_key"] = aws_secret_access_key
        self._session = aioboto3.Session(**session_kwargs)
        self._receipts: dict[str, str] = {}

    def _client(self) -> Any:
        return self._session.client("sqs")

    # ------------------------------------------------------------------ push

    async def push(self, record: JobRecord) -> None:
        delay = int(
            (record.available_at - datetime.now(UTC)).total_seconds()
        )
        delay = max(0, min(delay, self._max_delay_seconds))
        body = record.model_dump_json()
        async with self._client() as sqs:
            kwargs: dict[str, Any] = {
                "QueueUrl": self._queue_url,
                "MessageBody": body,
            }
            if delay > 0:
                kwargs["DelaySeconds"] = delay
            await sqs.send_message(**kwargs)

    # ------------------------------------------------------------------- pop

    async def pop(
        self,
        *,
        queues: tuple[str, ...] = ("default",),
        timeout: float = 1.0,
    ) -> JobRecord | None:
        # SQS knows about one queue URL per driver instance. The
        # ``queues`` tuple is ignored here — name-based prioritisation
        # is resolved at the supervisor level by running one SQSQueue
        # per priority bucket rather than multiplexing inside a single
        # driver (SQS has no cross-queue atomic pop).
        wait_seconds = max(0, min(20, int(timeout)))  # SQS caps at 20
        async with self._client() as sqs:
            response = await sqs.receive_message(
                QueueUrl=self._queue_url,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=wait_seconds,
                VisibilityTimeout=self._visibility_timeout,
            )
        messages = response.get("Messages", [])
        if not messages:
            return None
        msg = messages[0]
        record = JobRecord.model_validate_json(msg["Body"])
        self._receipts[record.id] = msg["ReceiptHandle"]
        return record

    # ------------------------------------------------------------------- size

    async def size(self, queue: str = "default") -> int:
        async with self._client() as sqs:
            response = await sqs.get_queue_attributes(
                QueueUrl=self._queue_url,
                AttributeNames=["ApproximateNumberOfMessages"],
            )
        attrs = response.get("Attributes", {})
        return int(attrs.get("ApproximateNumberOfMessages", 0))

    async def recent_size(self, queue: str = "default") -> int:
        # SQS keeps no recent-history ring — see ``record_completed``.
        return 0

    async def report_worker_count(
        self, queue: str, count: int, *, ttl_seconds: int = 30,
    ) -> None:
        # No shared-state surface for worker heartbeats on SQS.
        return None

    async def worker_counts(self) -> dict[str, int]:
        return {}

    async def forget_pending(
        self, queue: str, record_id: str,
    ) -> bool:
        # Need a receipt handle to delete a specific SQS message and
        # that handle is only produced by ReceiveMessage, which would
        # hide the message from real consumers. Not supported.
        return False

    async def record_completed(
        self,
        record: JobRecord,
        *,
        status: str,
        error: str | None = None,
    ) -> None:
        # SQS has no store for completed history — deleting the
        # message is the only "ack", and projects that need the
        # Recent admin panel should bind MemoryQueue or RedisQueue.
        return None

    async def recent_records(
        self, queue: str = "default", *, limit: int = 100, offset: int = 0,
    ) -> list[Any]:
        return []

    async def pending_records(
        self, queue: str = "default", *, limit: int = 100, offset: int = 0,
    ) -> list[JobRecord]:
        """SQS has no list-only primitive.

        ``ReceiveMessage`` is the only way to look at a message and
        it always consumes the message from the visibility window,
        which would hide real work from downstream consumers. Rather
        than risk that, the SQS driver reports an empty pending list
        — operators lose the per-message table but keep the
        ``size()`` counter that does work via
        ``ApproximateNumberOfMessages``.
        """
        return []

    # --------------------------------------------------------------- ack/fail

    async def ack(self, record: JobRecord) -> None:
        receipt = self._receipts.pop(record.id, None)
        if receipt is None:
            return  # nothing to ack — record was never popped through us
        async with self._client() as sqs:
            await sqs.delete_message(
                QueueUrl=self._queue_url, ReceiptHandle=receipt,
            )

    async def fail(self, record: JobRecord, error: str) -> None:
        """Route *record* to the DLQ (if configured) and delete from primary.

        Without a DLQ the message is simply deleted — the ``error``
        string is logged at the worker level but not stored in SQS.
        Applications that need a durable failed pool must configure a
        DLQ URL.
        """
        receipt = self._receipts.pop(record.id, None)
        async with self._client() as sqs:
            if self._dlq_url is not None:
                import json

                # Encode both the original record and the error alongside
                # each other so retry_failed() can restore the record and
                # failed_records() can surface the error.
                envelope = {
                    "record": record.model_dump_json(),
                    "error": error,
                }
                await sqs.send_message(
                    QueueUrl=self._dlq_url,
                    MessageBody=json.dumps(envelope),
                )
            if receipt is not None:
                await sqs.delete_message(
                    QueueUrl=self._queue_url, ReceiptHandle=receipt,
                )

    # ------------------------------------------------------------ failed pool

    async def failed_records(self) -> list[FailedJob]:
        self._require_dlq()
        import json

        out: list[FailedJob] = []
        async with self._client() as sqs:
            # Drain the DLQ non-destructively: peek with a short
            # visibility timeout so the messages re-appear quickly.
            while True:
                response = await sqs.receive_message(
                    QueueUrl=self._dlq_url,
                    MaxNumberOfMessages=10,
                    WaitTimeSeconds=0,
                    VisibilityTimeout=1,
                )
                messages = response.get("Messages", [])
                if not messages:
                    break
                for msg in messages:
                    envelope = json.loads(msg["Body"])
                    record = JobRecord.model_validate_json(envelope["record"])
                    out.append(
                        FailedJob(record=record, error=envelope.get("error", ""))
                    )
        return out

    async def retry_failed(self, record_id: str | None = None) -> int:
        self._require_dlq()
        import json

        moved = 0
        async with self._client() as sqs:
            while True:
                response = await sqs.receive_message(
                    QueueUrl=self._dlq_url,
                    MaxNumberOfMessages=10,
                    WaitTimeSeconds=0,
                    VisibilityTimeout=30,
                )
                messages = response.get("Messages", [])
                if not messages:
                    break
                for msg in messages:
                    envelope = json.loads(msg["Body"])
                    record = JobRecord.model_validate_json(envelope["record"])
                    if record_id is not None and record.id != record_id:
                        continue
                    # Reset attempts by rebuilding the record via copy.
                    fresh = record.model_copy(update={"attempts": 0})
                    await sqs.send_message(
                        QueueUrl=self._queue_url,
                        MessageBody=fresh.model_dump_json(),
                    )
                    await sqs.delete_message(
                        QueueUrl=self._dlq_url,
                        ReceiptHandle=msg["ReceiptHandle"],
                    )
                    moved += 1
                    if record_id is not None:
                        return moved
        return moved

    async def forget_failed(self, record_id: str) -> bool:
        self._require_dlq()
        import json

        async with self._client() as sqs:
            while True:
                response = await sqs.receive_message(
                    QueueUrl=self._dlq_url,
                    MaxNumberOfMessages=10,
                    WaitTimeSeconds=0,
                    VisibilityTimeout=30,
                )
                messages = response.get("Messages", [])
                if not messages:
                    return False
                for msg in messages:
                    envelope = json.loads(msg["Body"])
                    record = JobRecord.model_validate_json(envelope["record"])
                    if record.id == record_id:
                        await sqs.delete_message(
                            QueueUrl=self._dlq_url,
                            ReceiptHandle=msg["ReceiptHandle"],
                        )
                        return True

    async def flush_failed(self) -> int:
        self._require_dlq()
        assert self._dlq_url is not None
        async with self._client() as sqs:
            before = await self._approximate_size(sqs, self._dlq_url)
            await sqs.purge_queue(QueueUrl=self._dlq_url)
            return before

    async def clear_pending(self) -> int:
        async with self._client() as sqs:
            before = await self._approximate_size(sqs, self._queue_url)
            await sqs.purge_queue(QueueUrl=self._queue_url)
            return before

    async def prune_failed(self, before: datetime) -> int:
        """SQS has no native age-based pruning.

        Iterates the DLQ and deletes messages whose ``queued_at`` is
        older than *before*. Best-effort — messages still in flight
        during the scan are skipped this round.
        """
        self._require_dlq()
        import json

        removed = 0
        async with self._client() as sqs:
            response = await sqs.receive_message(
                QueueUrl=self._dlq_url,
                MaxNumberOfMessages=10,
                WaitTimeSeconds=0,
                VisibilityTimeout=30,
            )
            for msg in response.get("Messages", []):
                envelope = json.loads(msg["Body"])
                record = JobRecord.model_validate_json(envelope["record"])
                if record.queued_at < before:
                    await sqs.delete_message(
                        QueueUrl=self._dlq_url,
                        ReceiptHandle=msg["ReceiptHandle"],
                    )
                    removed += 1
        return removed

    # -------------------------------------------------------------- internals

    async def _approximate_size(self, sqs: Any, queue_url: str) -> int:
        response = await sqs.get_queue_attributes(
            QueueUrl=queue_url,
            AttributeNames=["ApproximateNumberOfMessages"],
        )
        return int(
            response.get("Attributes", {}).get("ApproximateNumberOfMessages", 0)
        )

    def _require_dlq(self) -> None:
        if self._dlq_url is None:
            raise FailedPoolUnavailableError(
                "SQSQueue requires a dlq_url for failed-pool operations. "
                "Pass dlq_url=... to the constructor."
            )
