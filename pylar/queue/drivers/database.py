"""SQLAlchemy-backed queue driver.

Persists job records into a single ``pylar_jobs`` table and failures
into ``pylar_failed_jobs``. The driver works against any SA-supported
database — when the application already runs on Postgres or SQLite,
adding a real persistent queue costs zero new infrastructure. The
trade-off vs Redis or SQS is latency: the driver polls the table for
due records rather than waiting on a blocking pop, so the worker is
configured with a poll interval that balances responsiveness against
load on the database.

Locking semantics
-----------------

Concurrent workers may compete for the same record. The driver
implements a *claim* round on every pop: it selects the next due
record's id, then issues an ``UPDATE`` that bumps a ``reserved_at``
column with a guard ``WHERE reserved_at IS NULL``. Only one worker's
update succeeds; the others see ``rowcount == 0`` and retry. This is
the same row-level dance Laravel's database queue driver uses, and it
works on every backend pylar's :class:`AsyncEngine` supports without
requiring backend-specific ``SELECT … FOR UPDATE SKIP LOCKED``
syntax.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Column as _Column
from sqlalchemy import (
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    case,
    delete,
    func,
    insert,
    literal,
    select,
    update,
)
from sqlalchemy.ext.asyncio import AsyncEngine

from pylar.queue.queue import FailedJob
from pylar.queue.record import JobRecord

# Standalone metadata so the queue tables do not bleed into the
# application's Model.metadata. Bootstrap creates them on first use.
_metadata = MetaData()

jobs_table = Table(
    "pylar_jobs",
    _metadata,
    _Column("id", String(36), primary_key=True),
    _Column("job_class", String(255), nullable=False),
    _Column("payload_json", Text, nullable=False),
    _Column("queue", String(64), nullable=False, default="default", index=True),
    _Column("attempts", Integer, nullable=False, default=0),
    _Column("queued_at", DateTime(timezone=True), nullable=False),
    _Column("available_at", DateTime(timezone=True), nullable=False),
    _Column("reserved_at", DateTime(timezone=True), nullable=True),
)

failed_jobs_table = Table(
    "pylar_failed_jobs",
    _metadata,
    _Column("id", String(36), primary_key=True),
    _Column("job_class", String(255), nullable=False),
    _Column("payload_json", Text, nullable=False),
    _Column("queue", String(64), nullable=False, default="default"),
    _Column("attempts", Integer, nullable=False),
    _Column("queued_at", DateTime(timezone=True), nullable=False),
    _Column("available_at", DateTime(timezone=True), nullable=False),
    _Column("error", Text, nullable=False),
    _Column("failed_at", DateTime(timezone=True), nullable=False),
)


class DatabaseQueue:
    """Queue driver backed by two SQL tables.

    *engine* is shared with the rest of the application. The driver
    opens its own short-lived connections so queue work never collides
    with the request-scoped session.
    """

    def __init__(
        self,
        engine: AsyncEngine,
        *,
        poll_interval: float = 0.5,
        reserve_timeout: int = 300,
    ) -> None:
        self._engine = engine
        self._poll_interval = poll_interval
        self._reserve_timeout = reserve_timeout

    async def bootstrap(self) -> None:
        """Create the queue tables if they do not yet exist."""
        async with self._engine.begin() as conn:
            await conn.run_sync(_metadata.create_all)

    # ------------------------------------------------------------------ push

    async def push(self, record: JobRecord) -> None:
        async with self._engine.begin() as conn:
            existing = (
                await conn.execute(
                    select(jobs_table.c.id).where(jobs_table.c.id == record.id)
                )
            ).first()
            values: dict[str, Any] = {
                "id": record.id,
                "job_class": record.job_class,
                "payload_json": record.payload_json,
                "queue": record.queue,
                "attempts": record.attempts,
                "queued_at": record.queued_at,
                "available_at": record.available_at,
                "reserved_at": None,
            }
            if existing is None:
                await conn.execute(insert(jobs_table).values(**values))
            else:
                # Retry path: the worker re-pushes the same id with a
                # bumped attempts count and a fresh available_at.
                await conn.execute(
                    update(jobs_table)
                    .where(jobs_table.c.id == record.id)
                    .values(
                        attempts=record.attempts,
                        available_at=record.available_at,
                        reserved_at=None,
                    )
                )

    # ------------------------------------------------------------------- pop

    async def pop(
        self,
        *,
        queues: tuple[str, ...] = ("default",),
        timeout: float = 1.0,
    ) -> JobRecord | None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            record = await self._claim_one(queues)
            if record is not None:
                return record
            remaining = deadline - loop.time()
            if remaining <= 0:
                return None
            await asyncio.sleep(min(self._poll_interval, remaining))

    async def _claim_one(self, queues: tuple[str, ...]) -> JobRecord | None:
        now = datetime.now(UTC)
        # First, release any jobs that have been reserved for longer
        # than reserve_timeout — these are from crashed workers.
        stale_cutoff = now - timedelta(seconds=self._reserve_timeout)
        async with self._engine.begin() as conn:
            await conn.execute(
                update(jobs_table)
                .where(jobs_table.c.reserved_at.is_not(None))
                .where(jobs_table.c.reserved_at <= stale_cutoff)
                .values(reserved_at=None)
            )
        # Priority order is encoded as a CASE expression so a single
        # SELECT walks every requested queue and prefers the leftmost.
        priority = case(
            *[(jobs_table.c.queue == name, literal(idx)) for idx, name in enumerate(queues)],
            else_=literal(len(queues)),
        )
        async with self._engine.begin() as conn:
            row = (
                await conn.execute(
                    select(
                        jobs_table.c.id,
                        jobs_table.c.job_class,
                        jobs_table.c.payload_json,
                        jobs_table.c.queue,
                        jobs_table.c.attempts,
                        jobs_table.c.queued_at,
                        jobs_table.c.available_at,
                    )
                    .where(jobs_table.c.reserved_at.is_(None))
                    .where(jobs_table.c.available_at <= now)
                    .where(jobs_table.c.queue.in_(queues))
                    .order_by(priority, jobs_table.c.available_at)
                    .limit(1)
                )
            ).first()
            if row is None:
                return None
            result = await conn.execute(
                update(jobs_table)
                .where(jobs_table.c.id == row.id)
                .where(jobs_table.c.reserved_at.is_(None))
                .values(reserved_at=now)
            )
            if (result.rowcount or 0) == 0:
                # Another worker beat us to this id — caller will retry.
                return None
            return JobRecord(
                id=row.id,
                job_class=row.job_class,
                payload_json=row.payload_json,
                queue=row.queue,
                attempts=row.attempts,
                queued_at=_as_utc(row.queued_at),
                available_at=_as_utc(row.available_at),
            )

    # --------------------------------------------------------------- terminal

    async def ack(self, record: JobRecord) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                delete(jobs_table).where(jobs_table.c.id == record.id)
            )

    async def fail(self, record: JobRecord, error: str) -> None:
        now = datetime.now(UTC)
        async with self._engine.begin() as conn:
            await conn.execute(
                delete(jobs_table).where(jobs_table.c.id == record.id)
            )
            await conn.execute(
                insert(failed_jobs_table).values(
                    id=record.id,
                    job_class=record.job_class,
                    payload_json=record.payload_json,
                    queue=record.queue,
                    attempts=record.attempts,
                    queued_at=record.queued_at,
                    available_at=record.available_at,
                    error=error,
                    failed_at=now,
                )
            )

    # ----------------------------------------------------------- failed pool

    async def failed_records(self) -> list[FailedJob]:
        async with self._engine.begin() as conn:
            rows = (
                await conn.execute(
                    select(
                        failed_jobs_table.c.id,
                        failed_jobs_table.c.job_class,
                        failed_jobs_table.c.payload_json,
                        failed_jobs_table.c.queue,
                        failed_jobs_table.c.attempts,
                        failed_jobs_table.c.queued_at,
                        failed_jobs_table.c.available_at,
                        failed_jobs_table.c.error,
                        failed_jobs_table.c.failed_at,
                    )
                )
            ).all()
        return [
            FailedJob(
                record=JobRecord(
                    id=row.id,
                    job_class=row.job_class,
                    payload_json=row.payload_json,
                    queue=row.queue,
                    attempts=row.attempts,
                    queued_at=_as_utc(row.queued_at),
                    available_at=_as_utc(row.available_at),
                ),
                error=row.error,
                failed_at=_as_utc(row.failed_at),
            )
            for row in rows
        ]

    async def retry_failed(self, record_id: str | None = None) -> int:
        async with self._engine.begin() as conn:
            base_select = select(
                failed_jobs_table.c.id,
                failed_jobs_table.c.job_class,
                failed_jobs_table.c.payload_json,
                failed_jobs_table.c.queue,
                failed_jobs_table.c.attempts,
                failed_jobs_table.c.queued_at,
                failed_jobs_table.c.available_at,
            )
            if record_id is not None:
                rows = (
                    await conn.execute(
                        base_select.where(failed_jobs_table.c.id == record_id)
                    )
                ).all()
            else:
                rows = (await conn.execute(base_select)).all()
            if not rows:
                return 0
            ids = [row.id for row in rows]
            now = datetime.now(UTC)
            for row in rows:
                await conn.execute(
                    insert(jobs_table).values(
                        id=row.id,
                        job_class=row.job_class,
                        payload_json=row.payload_json,
                        queue=row.queue,
                        attempts=row.attempts,
                        queued_at=row.queued_at,
                        available_at=now,
                        reserved_at=None,
                    )
                )
            await conn.execute(
                delete(failed_jobs_table).where(failed_jobs_table.c.id.in_(ids))
            )
            return len(rows)

    async def forget_failed(self, record_id: str) -> bool:
        async with self._engine.begin() as conn:
            result = await conn.execute(
                delete(failed_jobs_table).where(failed_jobs_table.c.id == record_id)
            )
            return (result.rowcount or 0) > 0

    async def flush_failed(self) -> int:
        async with self._engine.begin() as conn:
            result = await conn.execute(delete(failed_jobs_table))
            return result.rowcount or 0

    async def clear_pending(self) -> int:
        async with self._engine.begin() as conn:
            result = await conn.execute(delete(jobs_table))
            return result.rowcount or 0

    async def prune_failed(self, before: datetime) -> int:
        async with self._engine.begin() as conn:
            result = await conn.execute(
                delete(failed_jobs_table).where(failed_jobs_table.c.failed_at < before)
            )
            return result.rowcount or 0

    async def size(self, queue: str = "default") -> int:
        async with self._engine.begin() as conn:
            result = await conn.execute(
                select(func.count())
                .select_from(jobs_table)
                .where(jobs_table.c.queue == queue)
                .where(jobs_table.c.reserved_at.is_(None))
            )
            return int(result.scalar_one())

    async def recent_size(self, queue: str = "default") -> int:
        # No recent-history table — see ``record_completed`` below.
        return 0

    async def report_worker_count(
        self, queue: str, count: int, *, ttl_seconds: int = 30,
    ) -> None:
        # Database driver has no dedicated pool-heartbeat table; the
        # admin sees zeros for worker counts unless the app binds a
        # Redis-backed JobQueue for this particular reporting surface.
        return None

    async def worker_counts(self) -> dict[str, int]:
        return {}

    async def forget_pending(
        self, queue: str, record_id: str,
    ) -> bool:
        from sqlalchemy import delete

        async with self._engine.begin() as conn:
            result = await conn.execute(
                delete(jobs_table)
                .where(jobs_table.c.id == record_id)
                .where(jobs_table.c.queue == queue)
                .where(jobs_table.c.reserved_at.is_(None))
            )
            return bool(result.rowcount)

    async def record_completed(
        self,
        record: JobRecord,
        *,
        status: str,
        error: str | None = None,
    ) -> None:
        # The database driver stores pending and failed rows in
        # purpose-built tables but does not keep a completed-job
        # ring. Implementing one would be a meaningful schema change
        # (new table + retention index); callers who need that
        # history should bind RedisQueue or MemoryQueue as the
        # JobQueue — the admin UI treats an empty list as
        # "history not stored".
        return None

    async def recent_records(
        self, queue: str = "default", *, limit: int = 100, offset: int = 0,
    ) -> list[Any]:
        return []

    async def pending_records(
        self, queue: str = "default", *, limit: int = 100, offset: int = 0,
    ) -> list[JobRecord]:
        """Peek a page of pending rows ordered by queued_at (FIFO)."""
        async with self._engine.begin() as conn:
            result = await conn.execute(
                select(jobs_table)
                .where(jobs_table.c.queue == queue)
                .where(jobs_table.c.reserved_at.is_(None))
                .order_by(jobs_table.c.queued_at)
                .limit(limit)
                .offset(offset)
            )
            return [
                JobRecord(
                    id=row.id,
                    job_class=row.job_class,
                    payload_json=row.payload_json,
                    queue=row.queue,
                    attempts=row.attempts,
                    queued_at=_as_utc(row.queued_at),
                    available_at=_as_utc(row.available_at),
                )
                for row in result.all()
            ]


def _as_utc(value: datetime) -> datetime:
    """Coerce naive datetimes coming back from SQLite into UTC-aware ones."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
