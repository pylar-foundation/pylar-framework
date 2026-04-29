"""In-process queue driver — used for tests, single-process servers, and dev."""

from __future__ import annotations

import asyncio
import heapq
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from itertools import count

from pylar.queue.queue import FailedJob, RecentJob, RecentStatus
from pylar.queue.record import JobRecord


class MemoryQueue:
    """An async in-process driver with delayed-job, retry, and named queues.

    Records live in **per-queue** min-heaps keyed by
    ``(available_at, sequence)`` so a worker that pops always sees the
    next record that is *due* on its priority list. ``pop`` walks the
    requested queue list left-to-right and returns the first available
    record from the first non-empty bucket — the framework's priority
    semantics live entirely here, no fairness pass.

    The failed pool is one shared dict keyed by record id (failures
    are not bucketed by queue — operators need a single failed view
    regardless of which queue produced the record).
    """

    def __init__(
        self,
        *,
        recent_retention_seconds: int = 3600,
    ) -> None:
        # heaps[queue] — per-queue min-heap of (available_at, seq, record)
        self._heaps: dict[str, list[tuple[datetime, int, JobRecord]]] = defaultdict(list)
        self._counter = count()
        self._not_empty = asyncio.Condition()
        self._failed: dict[str, FailedJob] = {}
        self._acked: list[JobRecord] = []
        # Newest-last ring of terminal records per queue, pruned
        # lazily against ``_recent_retention`` on every read.
        self._recent: dict[str, list[RecentJob]] = defaultdict(list)
        self._recent_retention = recent_retention_seconds
        # Supervisor-reported live worker counts with per-queue
        # deadlines — same TTL semantics as the Redis driver so the
        # two behave the same in tests.
        self._worker_counts: dict[str, tuple[int, datetime]] = {}

    # ------------------------------------------------------------------ push

    async def push(self, record: JobRecord) -> None:
        async with self._not_empty:
            heapq.heappush(
                self._heaps[record.queue],
                (record.available_at, next(self._counter), record),
            )
            self._not_empty.notify_all()

    # ------------------------------------------------------------------- pop

    async def pop(
        self,
        *,
        queues: tuple[str, ...] = ("default",),
        timeout: float = 1.0,
    ) -> JobRecord | None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout

        async with self._not_empty:
            while True:
                now = datetime.now(UTC)

                # Walk priority list left-to-right; first due record wins.
                next_available: datetime | None = None
                for queue_name in queues:
                    heap = self._heaps.get(queue_name)
                    if not heap:
                        continue
                    available_at, _, record = heap[0]
                    if available_at <= now:
                        heapq.heappop(heap)
                        return record
                    if next_available is None or available_at < next_available:
                        next_available = available_at

                # Nothing due across the priority list — sleep until the
                # earliest future record or until the caller's deadline.
                if next_available is not None:
                    wait_seconds = max(
                        0.0,
                        min(
                            (next_available - now).total_seconds(),
                            deadline - loop.time(),
                        ),
                    )
                else:
                    wait_seconds = max(0.0, deadline - loop.time())

                if wait_seconds <= 0:
                    return None

                try:
                    await asyncio.wait_for(
                        self._not_empty.wait(), timeout=wait_seconds
                    )
                except TimeoutError:
                    if loop.time() >= deadline and not self._has_due_record(queues):
                        return None
                    # Otherwise loop and re-check the heap heads.

    def _has_due_record(self, queues: tuple[str, ...]) -> bool:
        now = datetime.now(UTC)
        for queue_name in queues:
            heap = self._heaps.get(queue_name)
            if heap and heap[0][0] <= now:
                return True
        return False

    # ------------------------------------------------------------- terminal

    async def ack(self, record: JobRecord) -> None:
        self._acked.append(record)

    async def fail(self, record: JobRecord, error: str) -> None:
        self._failed[record.id] = FailedJob(
            record=record, error=error, failed_at=datetime.now(UTC),
        )
        # Also drop a recent-history entry so the admin "Recent"
        # section can surface failed jobs alongside completed ones
        # without a separate fetch.
        await self.record_completed(record, status="failed", error=error)

    # ------------------------------------------------------------ failed pool

    async def failed_records(self) -> list[FailedJob]:
        return list(self._failed.values())

    async def retry_failed(self, record_id: str | None = None) -> int:
        if record_id is not None:
            entry = self._failed.pop(record_id, None)
            if entry is None:
                return 0
            await self.push(entry.record)
            return 1

        moved = list(self._failed.values())
        self._failed.clear()
        for entry in moved:
            await self.push(entry.record)
        return len(moved)

    async def forget_failed(self, record_id: str) -> bool:
        return self._failed.pop(record_id, None) is not None

    async def flush_failed(self) -> int:
        count = len(self._failed)
        self._failed.clear()
        return count

    async def clear_pending(self) -> int:
        async with self._not_empty:
            total = sum(len(heap) for heap in self._heaps.values())
            self._heaps.clear()
            return total

    async def prune_failed(self, before: datetime) -> int:
        stale = [
            rid for rid, entry in self._failed.items() if entry.failed_at < before
        ]
        for rid in stale:
            self._failed.pop(rid, None)
        return len(stale)

    async def size(self, queue: str = "default") -> int:
        return len(self._heaps.get(queue, []))

    async def recent_size(self, queue: str = "default") -> int:
        self._prune_recent(queue)
        return len(self._recent.get(queue, []))

    async def pending_records(
        self, queue: str = "default", *, limit: int = 100, offset: int = 0,
    ) -> list[JobRecord]:
        """Peek a page of pending records without popping them.

        Sorted by ``(available_at, insertion order)`` — the same
        ordering ``pop`` would yield. Iterating over the raw heap
        without touching it keeps the queue state immutable.
        """
        heap = self._heaps.get(queue, [])
        ordered = sorted(heap, key=lambda entry: (entry[0], entry[1]))
        window = ordered[offset : offset + limit]
        return [record for (_, _, record) in window]

    async def forget_pending(
        self, queue: str, record_id: str,
    ) -> bool:
        import heapq

        heap = self._heaps.get(queue)
        if not heap:
            return False
        kept = [entry for entry in heap if entry[2].id != record_id]
        if len(kept) == len(heap):
            return False
        heapq.heapify(kept)
        self._heaps[queue] = kept
        return True

    # ----------------------------------------------------------- recent pool

    async def record_completed(
        self,
        record: JobRecord,
        *,
        status: RecentStatus,
        error: str | None = None,
    ) -> None:
        self._recent[record.queue].append(
            RecentJob(
                record=record,
                status=status,
                completed_at=datetime.now(UTC),
                error=error,
            ),
        )
        # Opportunistic prune so the bucket never grows unbounded
        # even if nobody reads it.
        self._prune_recent(record.queue)

    async def recent_records(
        self, queue: str = "default", *, limit: int = 100, offset: int = 0,
    ) -> list[RecentJob]:
        self._prune_recent(queue)
        bucket = self._recent.get(queue, [])
        # Newest first.
        newest_first = list(reversed(bucket))
        return newest_first[offset : offset + limit]

    def _prune_recent(self, queue: str) -> None:
        bucket = self._recent.get(queue)
        if not bucket:
            return
        cutoff = datetime.now(UTC) - timedelta(seconds=self._recent_retention)
        self._recent[queue] = [r for r in bucket if r.completed_at >= cutoff]

    # ----------------------------------------------------------- worker pool

    async def report_worker_count(
        self, queue: str, count: int, *, ttl_seconds: int = 30,
    ) -> None:
        expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
        self._worker_counts[queue] = (count, expires_at)

    async def worker_counts(self) -> dict[str, int]:
        now = datetime.now(UTC)
        snapshot: dict[str, int] = {}
        expired: list[str] = []
        for name, (worker_count, expires_at) in self._worker_counts.items():
            if expires_at < now:
                expired.append(name)
                continue
            snapshot[name] = worker_count
        for name in expired:
            self._worker_counts.pop(name, None)
        return snapshot

    # ----------------------------------------------------------- introspection

    @property
    def acked(self) -> list[JobRecord]:
        """Records successfully processed by a worker. Test affordance."""
        return list(self._acked)

    @property
    def failed(self) -> list[tuple[JobRecord, str]]:
        """Failed records together with the rendered error message."""
        return [(entry.record, entry.error) for entry in self._failed.values()]

    def qsize(self) -> int:
        """Total number of pending records across every queue."""
        return sum(len(heap) for heap in self._heaps.values())
