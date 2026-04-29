"""The :class:`JobQueue` Protocol that every driver implements."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, Protocol, runtime_checkable

from pylar.queue.record import JobRecord


def _utc_now() -> datetime:
    return datetime.now(UTC)


#: Terminal job states surfaced on the "Recent jobs" admin panel.
RecentStatus = Literal["completed", "failed", "cancelled"]


@dataclass(frozen=True, slots=True)
class RecentJob:
    """A terminal record kept for a short window after it left the pipeline.

    Powers the admin panel's "Recent jobs" section and matches the
    way Horizon surfaces the last N minutes of activity regardless
    of outcome. Drivers that implement :meth:`JobQueue.recent_records`
    yield one of these per job that recently completed, failed, or
    was cancelled; a driver that cannot store history (SQS) simply
    returns an empty list.

    ``completed_at`` is when the job *left* the queue — after ack,
    after a worker moved it to the failed pool, or after the admin
    "Cancel" button fired. The TTL the driver enforces on the
    recent history is measured against this timestamp.
    """

    record: JobRecord
    status: RecentStatus
    completed_at: datetime
    error: str | None = None


@dataclass(frozen=True, slots=True)
class FailedJob:
    """A record that exhausted its retry budget plus the captured error.

    Surfaced via :meth:`JobQueue.failed_records` so the ``queue:failed``
    and ``queue:retry`` commands can list and re-queue them. Drivers
    are free to store the data however they like (in-memory list,
    a SQL ``failed_jobs`` table, a Redis list); the contract here is
    just the shape returned to the operator.

    ``failed_at`` lets ``queue:prune-failed`` drop records older than
    a given timestamp — matching Laravel's pruning semantics.
    """

    record: JobRecord
    error: str
    failed_at: datetime = field(default_factory=_utc_now)


@runtime_checkable
class JobQueue(Protocol):
    """The minimum surface a queue driver must expose.

    Pylar keeps the contract small so swapping in-memory for database /
    Redis is a single container rebinding. Six methods:

    * ``push`` — enqueue a record (immediate or delayed via
      ``record.available_at``).
    * ``pop`` — wait up to ``timeout`` seconds for a record whose
      ``available_at`` is in the past, or return ``None`` on miss.
    * ``ack`` / ``fail`` — terminal states for a popped record.
    * ``failed_records`` / ``retry_failed`` — operator surface backing
      the ``queue:failed`` and ``queue:retry`` commands.
    """

    async def push(self, record: JobRecord) -> None:
        """Append *record* to its bucket (``record.queue``)."""
        ...

    async def pop(
        self,
        *,
        queues: tuple[str, ...] = ("default",),
        timeout: float = 1.0,
    ) -> JobRecord | None:
        """Pop the next due record from *queues*, in priority order.

        Walks *queues* left-to-right and returns the first available
        record from the first non-empty bucket. Waits up to *timeout*
        seconds total for at least one bucket to produce a record;
        returns ``None`` if every bucket stays empty for the duration.
        """
        ...

    async def size(self, queue: str = "default") -> int:
        """Return the number of pending records in *queue*.

        Used by :class:`pylar.queue.QueueSupervisor` for autoscaling
        decisions and by operators for ad-hoc backlog inspection.
        """
        ...

    async def recent_size(self, queue: str = "default") -> int:
        """Return the number of records currently in the recent pool.

        Mirrors :meth:`size` but for the terminal-history view the
        admin panel paginates through. Drivers that cannot retain
        history (SQS) return ``0``.
        """
        ...

    async def pending_records(
        self, queue: str = "default", *, limit: int = 100, offset: int = 0,
    ) -> list[JobRecord]:
        """Peek a page of pending records without popping them.

        Powers the admin panel's "Pending jobs" table — operators
        need to see *what* is waiting, not just *how many*. Drivers
        return records in roughly the order ``pop`` would yield them
        (FIFO for lists, queued_at ASC for tables). *offset* skips
        that many records at the head so callers can page through
        deeper windows. Returning ``[]`` is a valid answer for
        driver backends that cannot enumerate without consuming
        records, such as SQS.
        """
        ...

    async def ack(self, record: JobRecord) -> None:
        """Mark *record* as successfully processed."""
        ...

    async def fail(self, record: JobRecord, error: str) -> None:
        """Mark *record* as failed and store *error* for inspection."""
        ...

    async def failed_records(self) -> list[FailedJob]:
        """Return every record currently parked in the failed pool."""
        ...

    async def retry_failed(self, record_id: str | None = None) -> int:
        """Re-queue failed records.

        ``None`` re-queues every failed record; passing a record id
        re-queues only that one. Returns the number of records moved.
        """
        ...

    async def forget_failed(self, record_id: str) -> bool:
        """Drop a single failed record. Returns ``True`` if it existed."""
        ...

    async def flush_failed(self) -> int:
        """Drop every record in the failed pool. Returns the number removed."""
        ...

    async def clear_pending(self) -> int:
        """Drop every pending (not-yet-processed) record. Returns the count."""
        ...

    async def forget_pending(
        self, queue: str, record_id: str,
    ) -> bool:
        """Drop a single pending record from *queue* without running it.

        Powers the admin panel's per-job "Cancel" button and any
        operator workflow that needs to pull a scheduled-but-not-yet-
        reserved record out of the backlog. Returns ``True`` when a
        record matched, ``False`` otherwise. Drivers that cannot
        enumerate without consuming records (SQS) may always return
        ``False``.
        """
        ...

    async def record_completed(
        self,
        record: JobRecord,
        *,
        status: RecentStatus,
        error: str | None = None,
    ) -> None:
        """Store *record* in the recent-history pool with its terminal status.

        Called by the worker after a successful ack (status
        ``"completed"``), by :meth:`fail` after a final failure
        (status ``"failed"``), and by the admin cancel flow (status
        ``"cancelled"``). Drivers enforce their own TTL so the pool
        stays small — one hour by default. Drivers that cannot
        retain history (SQS) treat this as a no-op.
        """
        ...

    async def recent_records(
        self, queue: str = "default", *, limit: int = 100, offset: int = 0,
    ) -> list[RecentJob]:
        """Return a page of recently-terminal records, newest first.

        Mirrors the admin panel's "Recent jobs" view. Records older
        than the driver's retention window are not returned — they
        may or may not have been physically removed yet, that is a
        driver-internal decision. *offset* skips that many records
        from the head (newest side) for pagination.
        """
        ...

    async def prune_failed(self, before: datetime) -> int:
        """Drop failed records whose ``failed_at`` is older than *before*."""
        ...

    async def report_worker_count(
        self, queue: str, count: int, *, ttl_seconds: int = 30,
    ) -> None:
        """Publish the supervisor's current live worker count for *queue*.

        Called by :class:`QueueSupervisor` on every tick so the admin
        panel can show the live pool size next to the queue policy.
        Drivers attach *ttl_seconds* to the value so a stalled
        supervisor silently stops contributing — the admin then shows
        0 rather than a frozen snapshot. Drivers that cannot share
        state across processes (pure in-memory) store it locally and
        accept that multi-process deployments will always see 0.
        """
        ...

    async def worker_counts(self) -> dict[str, int]:
        """Snapshot of ``{queue: live worker count}`` across every pool.

        Aggregates whatever non-expired values
        :meth:`report_worker_count` has stored. Returns an empty dict
        when no supervisor has reported yet. The admin panel keys off
        this map to render its per-queue "Workers" column.
        """
        ...
