"""Redis-backed queue driver — one list per named queue.

Pending records live in per-queue Redis lists
(``{prefix}:pending:<queue>``) so the priority-pop semantics are
expressible as a single ``BRPOP`` over the requested key list. A
processing hash (``{prefix}:processing``) tracks in-flight jobs;
``ack`` removes them, ``fail`` moves them to the failed list. Crashed
workers are recovered by scanning the processing hash for entries
older than ``reserve_timeout`` and pushing them back to the
appropriate per-queue pending list.

Install via ``pylar[queue-redis]`` (shares the ``redis>=5.0`` dep
with ``pylar[cache-redis]`` and ``pylar[session-redis]``).
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any

try:
    from redis.asyncio import Redis
except ImportError:  # pragma: no cover
    raise ImportError(
        "RedisQueue requires the 'redis' package. "
        "Install with: pip install 'pylar[queue-redis]'"
    ) from None

from pylar.queue.queue import FailedJob, RecentJob, RecentStatus
from pylar.queue.record import JobRecord


class RedisQueue:
    """Queue driver backed by Redis lists.

    *client* is a ``redis.asyncio.Redis`` instance. *prefix*
    namespaces every key so multiple applications can share a Redis
    database.
    """

    def __init__(
        self,
        client: Redis,
        *,
        prefix: str = "pylar:queue",
        reserve_timeout: int = 300,
        recent_retention_seconds: int = 3600,
    ) -> None:
        self._client = client
        self._prefix = prefix
        self._reserve_timeout = reserve_timeout
        self._processing = f"{prefix}:processing"
        self._failed = f"{prefix}:failed"
        self._delayed = f"{prefix}:delayed"
        # One sorted set per queue, scored by unix timestamp. We
        # prune below the TTL window on every write so the set
        # never grows without bound.
        self._recent_retention = recent_retention_seconds

    def _pending_key(self, queue: str) -> str:
        return f"{self._prefix}:pending:{queue}"

    def _workers_key(self, queue: str) -> str:
        return f"{self._prefix}:workers:{queue}"

    # ------------------------------------------------------------------ push

    async def push(self, record: JobRecord) -> None:
        data = record.model_dump_json()
        delay = (record.available_at - datetime.now(UTC)).total_seconds()
        if delay > 0:
            # Delayed records share a single sorted set keyed by
            # available_at — promotion fans them back out to per-queue
            # pending lists by reading record.queue at promote time.
            await self._client.zadd(self._delayed, {data: record.available_at.timestamp()})
        else:
            await self._client.lpush(self._pending_key(record.queue), data)

    # ------------------------------------------------------------------- pop

    async def pop(
        self,
        *,
        queues: tuple[str, ...] = ("default",),
        timeout: float = 1.0,
    ) -> JobRecord | None:
        # First, promote any delayed jobs that are now due.
        await self._promote_delayed()
        # Recover stale processing jobs (crashed workers).
        await self._recover_stale()

        keys = [self._pending_key(q) for q in queues]
        # BRPOP accepts a list of keys; it walks them in declared
        # order and pops from the first non-empty list, blocking up
        # to *timeout* seconds for any of them to become non-empty.
        result = await self._client.brpop(keys, timeout=max(1, int(timeout)))
        if result is None:
            return None
        _, raw = result
        record = JobRecord.model_validate_json(raw)
        await self._client.hset(
            self._processing,
            record.id,
            json.dumps({
                "data": raw.decode() if isinstance(raw, bytes) else raw,
                "queue": record.queue,
                "reserved_at": time.time(),
            }),
        )
        return record

    # --------------------------------------------------------------- terminal

    async def ack(self, record: JobRecord) -> None:
        await self._client.hdel(self._processing, record.id)

    async def fail(self, record: JobRecord, error: str) -> None:
        await self._client.hdel(self._processing, record.id)
        entry = {
            "record": record.model_dump_json(),
            "error": error,
            "failed_at": datetime.now(UTC).isoformat(),
        }
        await self._client.lpush(self._failed, json.dumps(entry))
        await self.record_completed(record, status="failed", error=error)

    # ----------------------------------------------------------- failed pool

    async def failed_records(self) -> list[FailedJob]:
        raw_list = await self._client.lrange(self._failed, 0, -1)
        results: list[FailedJob] = []
        for raw in raw_list:
            entry = json.loads(raw)
            record = JobRecord.model_validate_json(entry["record"])
            failed_at_raw = entry.get("failed_at")
            failed_at = (
                datetime.fromisoformat(failed_at_raw)
                if failed_at_raw is not None
                else datetime.now(UTC)
            )
            results.append(
                FailedJob(record=record, error=entry["error"], failed_at=failed_at)
            )
        return results

    async def retry_failed(self, record_id: str | None = None) -> int:
        if record_id is not None:
            return await self._retry_one(record_id)
        return await self._retry_all()

    async def _retry_one(self, record_id: str) -> int:
        raw_list = await self._client.lrange(self._failed, 0, -1)
        for raw in raw_list:
            entry = json.loads(raw)
            record = JobRecord.model_validate_json(entry["record"])
            if record.id == record_id:
                await self._client.lrem(self._failed, 1, raw)
                await self._client.lpush(self._pending_key(record.queue), entry["record"])
                return 1
        return 0

    async def _retry_all(self) -> int:
        count = 0
        while True:
            raw = await self._client.rpop(self._failed)
            if raw is None:
                break
            entry = json.loads(raw)
            record = JobRecord.model_validate_json(entry["record"])
            await self._client.lpush(self._pending_key(record.queue), entry["record"])
            count += 1
        return count

    async def forget_failed(self, record_id: str) -> bool:
        raw_list = await self._client.lrange(self._failed, 0, -1)
        for raw in raw_list:
            entry = json.loads(raw)
            record = JobRecord.model_validate_json(entry["record"])
            if record.id == record_id:
                await self._client.lrem(self._failed, 1, raw)
                return True
        return False

    async def flush_failed(self) -> int:
        size = int(await self._client.llen(self._failed))
        await self._client.delete(self._failed)
        return size

    async def clear_pending(self) -> int:
        # Match every per-queue pending list and zero them out.
        keys: list[bytes] = []
        cursor: int = 0
        pattern = f"{self._prefix}:pending:*"
        while True:
            cursor, batch = await self._client.scan(cursor, match=pattern, count=100)
            keys.extend(batch)
            if cursor == 0:
                break
        total = 0
        for key in keys:
            total += int(await self._client.llen(key))
            await self._client.delete(key)
        # Also drop delayed records — they are conceptually pending.
        total += int(await self._client.zcard(self._delayed))
        await self._client.delete(self._delayed)
        return total

    async def prune_failed(self, before: datetime) -> int:
        raw_list = await self._client.lrange(self._failed, 0, -1)
        removed = 0
        for raw in raw_list:
            entry = json.loads(raw)
            failed_at_raw = entry.get("failed_at")
            if failed_at_raw is None:
                continue
            failed_at = datetime.fromisoformat(failed_at_raw)
            if failed_at < before:
                await self._client.lrem(self._failed, 1, raw)
                removed += 1
        return removed

    async def size(self, queue: str = "default") -> int:
        return int(await self._client.llen(self._pending_key(queue)))

    async def recent_size(self, queue: str = "default") -> int:
        import time

        key = self._recent_key(queue)
        cutoff = time.time() - self._recent_retention
        # ZCOUNT over the live retention window — stale entries that
        # haven't been pruned yet don't skew the count.
        return int(await self._client.zcount(key, cutoff, "+inf"))

    def _recent_key(self, queue: str) -> str:
        return f"{self._prefix}:recent:{queue}"

    async def record_completed(
        self,
        record: JobRecord,
        *,
        status: RecentStatus,
        error: str | None = None,
    ) -> None:
        """Append to the per-queue sorted set + prune in one pipeline.

        Score is the unix timestamp so ``ZREMRANGEBYSCORE`` drops
        stale entries in O(log N). Keys carry a matching EXPIRE so
        a queue that stops receiving history eventually stops
        existing at all.
        """
        import time

        key = self._recent_key(record.queue)
        now = time.time()
        cutoff = now - self._recent_retention
        entry = json.dumps({
            "record": record.model_dump_json(),
            "status": status,
            "completed_at": datetime.now(UTC).isoformat(),
            "error": error,
        })
        async with self._client.pipeline(transaction=False) as pipe:
            pipe.zadd(key, {entry: now})
            pipe.zremrangebyscore(key, 0, cutoff)
            # +1 on the TTL so the key doesn't expire mid-flight on
            # a slow writer; a periodic re-EXPIRE is cheap either way.
            pipe.expire(key, self._recent_retention + 60)
            await pipe.execute()

    async def recent_records(
        self, queue: str = "default", *, limit: int = 100, offset: int = 0,
    ) -> list[RecentJob]:
        """Pull a page of freshest entries via ``ZREVRANGEBYSCORE``."""
        import time

        key = self._recent_key(queue)
        cutoff = time.time() - self._recent_retention
        raw_entries = await self._client.zrevrangebyscore(
            key, "+inf", cutoff, start=offset, num=limit,
        )
        results: list[RecentJob] = []
        for raw in raw_entries:
            data = raw.decode() if isinstance(raw, bytes) else raw
            try:
                payload = json.loads(data)
                record = JobRecord.model_validate_json(payload["record"])
                completed_at = datetime.fromisoformat(payload["completed_at"])
            except Exception:
                continue
            results.append(
                RecentJob(
                    record=record,
                    status=payload.get("status", "completed"),
                    completed_at=completed_at,
                    error=payload.get("error"),
                ),
            )
        return results

    async def forget_pending(
        self, queue: str, record_id: str,
    ) -> bool:
        """Scan the pending list and remove by id — O(N) but fine for admin ops."""
        key = self._pending_key(queue)
        raw_list = await self._client.lrange(key, 0, -1)
        for raw in raw_list:
            data = raw.decode() if isinstance(raw, bytes) else raw
            try:
                record = JobRecord.model_validate_json(data)
            except Exception:
                continue
            if record.id == record_id:
                await self._client.lrem(key, 1, raw)
                return True
        return False

    async def pending_records(
        self, queue: str = "default", *, limit: int = 100, offset: int = 0,
    ) -> list[JobRecord]:
        """Peek a page of pending records via ``LRANGE`` — non-destructive.

        Redis lists are pushed to the head (LPUSH) and popped from
        the tail (BRPOP), so the next-to-pop records live at indices
        ``-size..-1``. To produce a stable offset/limit window in
        pop-order we fetch the full list once and slice in Python.
        The recent-jobs pool lives in a sorted set and paginates
        cheaply, so the O(N) fetch here is bounded by the backlog
        the admin actually looks at.
        """
        key = self._pending_key(queue)
        raw_list = await self._client.lrange(key, 0, -1)
        # LPUSH/BRPOP semantics mean the tail of the list is
        # logically the head of the queue — reverse so element 0 is
        # the next-to-pop record.
        in_order = list(reversed(raw_list))
        window = in_order[offset : offset + limit]
        records: list[JobRecord] = []
        for raw in window:
            data = raw.decode() if isinstance(raw, bytes) else raw
            try:
                records.append(JobRecord.model_validate_json(data))
            except Exception:
                continue
        return records

    # ----------------------------------------------------------- internals

    async def _promote_delayed(self) -> None:
        """Move delayed jobs whose time has come to the per-queue lists."""
        now = time.time()
        due = await self._client.zrangebyscore(self._delayed, "-inf", now)
        if not due:
            return
        pipe = self._client.pipeline()
        for item in due:
            record = JobRecord.model_validate_json(item)
            pipe.lpush(self._pending_key(record.queue), item)
            pipe.zrem(self._delayed, item)
        await pipe.execute()

    async def _recover_stale(self) -> None:
        """Re-queue jobs stuck in processing (crashed worker)."""
        all_items: dict[Any, Any] = await self._client.hgetall(self._processing)
        cutoff = time.time() - self._reserve_timeout
        for record_id, meta_raw in all_items.items():
            meta = json.loads(meta_raw)
            if meta.get("reserved_at", 0) < cutoff:
                await self._client.hdel(self._processing, record_id)
                queue = meta.get("queue", "default")
                await self._client.lpush(self._pending_key(queue), meta["data"])

    # ----------------------------------------------------------- worker pool

    async def report_worker_count(
        self, queue: str, count: int, *, ttl_seconds: int = 30,
    ) -> None:
        """Store the live worker count for *queue* with TTL.

        One string key per queue — ``SET key value EX ttl`` so the
        count self-expires if the supervisor dies. Admin reads via
        :meth:`worker_counts` using ``SCAN`` + ``MGET``.
        """
        await self._client.set(
            self._workers_key(queue), count, ex=max(1, ttl_seconds),
        )

    async def worker_counts(self) -> dict[str, int]:
        pattern = f"{self._prefix}:workers:*"
        cursor: int = 0
        keys: list[bytes] = []
        while True:
            cursor, batch = await self._client.scan(cursor, match=pattern, count=100)
            keys.extend(batch)
            if cursor == 0:
                break
        if not keys:
            return {}
        values = await self._client.mget(keys)
        counts: dict[str, int] = {}
        prefix = f"{self._prefix}:workers:"
        for raw_key, raw_value in zip(keys, values, strict=False):
            if raw_value is None:
                continue
            key = raw_key.decode() if isinstance(raw_key, bytes) else raw_key
            value = raw_value.decode() if isinstance(raw_value, bytes) else raw_value
            try:
                counts[key.removeprefix(prefix)] = int(value)
            except ValueError:
                continue
        return counts
