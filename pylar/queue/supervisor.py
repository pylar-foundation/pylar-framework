"""``QueueSupervisor`` — autoscaling pool of workers across named queues.

The supervisor sits where Laravel's Horizon does: one long-running
process spawns and reaps :class:`Worker` instances per named queue
based on the :class:`QueueConfig` policy bound for that queue. Each
managed worker is its own asyncio task subscribed to exactly one
queue (we deliberately keep the worker→queue mapping flat — operators
who want a single worker to drain a priority list should keep using
``queue:work --queue=high,default,low`` directly).

Scaling decisions are taken once per ``scale_cooldown_seconds``:

* **scale up** when the queue's pending depth (``JobQueue.size``)
  reaches ``scale_threshold`` and the current worker count is below
  ``max_workers``.
* **scale down** when the queue has been empty for one full
  cooldown window and the current worker count is above
  ``min_workers``.

Cooldown is per-queue so a burst on ``high`` doesn't reset the scale
clock on ``low``. Stops are cooperative: workers finish their current
job before exiting, bounded by the worker's own ``drain_timeout``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from pylar.foundation.container import Container
from pylar.queue.config import QueueConfig, QueuesConfig
from pylar.queue.queue import JobQueue
from pylar.queue.worker import Worker

_logger = logging.getLogger("pylar.queue.supervisor")


#: Callable invoked for every worker the supervisor spawns. Lets the
#: CLI wire per-job logging, metrics, etc. onto each new worker using
#: the ``on_processing`` / ``on_processed`` / ``on_failed`` hooks — so
#: a supervisor-run pool emits the same Horizon-style log lines as
#: ``queue:work`` does, with the queue name surfaced in each record.
WorkerSpawnHook = Callable[[Worker, str], None]


#: Callable invoked when a pool's worker count changes. Arguments:
#: queue name, worker count *before* the change, worker count *after*,
#: and a short human reason (``"depth=55"``, ``"idle"``, ``"floor"``).
#: The CLI uses this to print ``Scaled low: 1 → 2 (depth=55)`` lines
#: in the same stream as per-job logs so the operator can see why the
#: pool just grew.
ScaleEventHook = Callable[[str, int, int, str], None]


@dataclass
class _ManagedWorker:
    """One supervisor-owned worker task, bookkeeping for graceful stop."""

    worker: Worker
    task: asyncio.Task[None]


@dataclass
class _PoolState:
    """Per-queue pool: live workers + the timestamp of the last decision."""

    config: QueueConfig
    workers: list[_ManagedWorker] = field(default_factory=list)
    empty_since: datetime | None = None
    last_scaled_at: datetime | None = None


class QueueSupervisor:
    """Long-running orchestrator that maintains ``min_workers ≤ N ≤ max_workers``
    workers per declared queue and scales the count by backlog depth.
    """

    def __init__(
        self,
        queue: JobQueue,
        container: Container,
        queues_config: QueuesConfig,
        *,
        poll_seconds: float = 1.0,
        on_worker_spawn: WorkerSpawnHook | None = None,
        on_scale: ScaleEventHook | None = None,
    ) -> None:
        self._queue = queue
        self._container = container
        self._queues_config = queues_config
        self._poll_seconds = poll_seconds
        self._stopping = False
        self._pools: dict[str, _PoolState] = {}
        self._on_worker_spawn = on_worker_spawn
        self._on_scale = on_scale

    @property
    def is_stopping(self) -> bool:
        return self._stopping

    def stop(self) -> None:
        self._stopping = True

    def pool_sizes(self) -> dict[str, int]:
        """Snapshot of {queue: live worker count} — used by tests & status."""
        return {name: len(pool.workers) for name, pool in self._pools.items()}

    # ----------------------------------------------------------- lifecycle

    async def run(self) -> None:
        """Spin up the minimum worker counts and supervise until stopped."""
        for name, cfg in self._queues_config.queues.items():
            self._pools[name] = _PoolState(config=cfg)
            before = 0
            for _ in range(cfg.min_workers):
                self._spawn_worker(name)
            after = len(self._pools[name].workers)
            if after != before:
                self._emit_scale(name, before, after, "startup")

        try:
            while not self._stopping:
                await self._tick()
                await asyncio.sleep(self._poll_seconds)
        finally:
            await self._drain_all()

    # ----------------------------------------------------------- scaling

    async def _tick(self) -> None:
        now = datetime.now(UTC)
        for name, pool in self._pools.items():
            await self._reconcile(name, pool, now)
        await self._publish_pool_sizes()

    async def _publish_pool_sizes(self) -> None:
        """Broadcast live pool sizes so the admin panel can render them.

        TTL is sized generously above ``poll_seconds`` so a single
        missed tick doesn't drop the count to zero, but short enough
        that an exiting supervisor is visible within a few seconds.
        """
        ttl = max(10, int(self._poll_seconds * 10))
        for name, pool in self._pools.items():
            try:
                await self._queue.report_worker_count(
                    name, len(pool.workers), ttl_seconds=ttl,
                )
            except Exception:
                _logger.exception(
                    "queue=%s failed to publish pool size", name,
                )

    async def _reconcile(
        self, name: str, pool: _PoolState, now: datetime
    ) -> None:
        # Reap any worker tasks that finished on their own (errors
        # propagated, signals, etc.) so live count stays accurate.
        pool.workers = [w for w in pool.workers if not w.task.done()]

        depth = await self._queue.size(name)

        if depth == 0:
            if pool.empty_since is None:
                pool.empty_since = now
        else:
            pool.empty_since = None

        cfg = pool.config

        # Cooldown gate — scaling decisions throttle to one per window.
        if pool.last_scaled_at is not None:
            elapsed = (now - pool.last_scaled_at).total_seconds()
            if elapsed < cfg.scale_cooldown_seconds:
                # Below the floor, refill *immediately* — losing a worker
                # to an exception shouldn't wait out the cooldown.
                self._enforce_floor(name, pool)
                return

        if depth >= cfg.scale_threshold and len(pool.workers) < cfg.max_workers:
            before = len(pool.workers)
            self._spawn_worker(name)
            after = len(pool.workers)
            pool.last_scaled_at = now
            _logger.info(
                "queue=%s scaled up to %d worker(s) (depth=%d)",
                name, after, depth,
            )
            self._emit_scale(name, before, after, f"depth={depth}")
            return

        if (
            len(pool.workers) > cfg.min_workers
            and pool.empty_since is not None
            and (now - pool.empty_since).total_seconds() >= cfg.scale_cooldown_seconds
        ):
            before = len(pool.workers)
            await self._retire_worker(name, pool)
            after = len(pool.workers)
            pool.last_scaled_at = now
            pool.empty_since = now  # restart the empty clock
            _logger.info(
                "queue=%s scaled down to %d worker(s) (idle window expired)",
                name, after,
            )
            self._emit_scale(name, before, after, "idle")
            return

        # No scaling action — still enforce the floor in case a worker died.
        self._enforce_floor(name, pool)

    def _enforce_floor(self, name: str, pool: _PoolState) -> None:
        before = len(pool.workers)
        while len(pool.workers) < pool.config.min_workers:
            self._spawn_worker(name)
        after = len(pool.workers)
        if after != before:
            self._emit_scale(name, before, after, "floor")

    def _emit_scale(
        self, name: str, before: int, after: int, reason: str,
    ) -> None:
        if self._on_scale is not None:
            self._on_scale(name, before, after, reason)

    # --------------------------------------------------------- worker mgmt

    def _spawn_worker(self, queue_name: str) -> None:
        worker = Worker(
            self._queue,
            self._container,
            queues=(queue_name,),
        )
        if self._on_worker_spawn is not None:
            self._on_worker_spawn(worker, queue_name)

        async def _slot() -> None:
            while not worker.is_stopping and not self._stopping:
                try:
                    await worker.process_next(timeout=self._poll_seconds)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    _logger.exception(
                        "queue=%s worker process_next raised — continuing",
                        queue_name,
                    )

        task = asyncio.create_task(_slot(), name=f"queue-worker:{queue_name}")
        self._pools[queue_name].workers.append(
            _ManagedWorker(worker=worker, task=task)
        )

    async def _retire_worker(self, name: str, pool: _PoolState) -> None:
        if not pool.workers:
            return
        # Remove the most-recently-spawned worker first so long-running
        # workers warmed by JIT / connection pools stay around.
        managed = pool.workers.pop()
        managed.worker.stop()
        try:
            await asyncio.wait_for(managed.task, timeout=self._poll_seconds * 2)
        except (TimeoutError, asyncio.CancelledError):
            managed.task.cancel()

    async def _drain_all(self) -> None:
        """On stop, ask every worker to finish its current job and exit."""
        all_tasks: list[asyncio.Task[None]] = []
        for pool in self._pools.values():
            for managed in pool.workers:
                managed.worker.stop()
                all_tasks.append(managed.task)
            pool.workers.clear()
        if not all_tasks:
            return
        # Bound the drain so a stuck worker doesn't block forever.
        _done, pending = await asyncio.wait(
            all_tasks, timeout=max(5.0, self._poll_seconds * 5)
        )
        for task in pending:
            task.cancel()
