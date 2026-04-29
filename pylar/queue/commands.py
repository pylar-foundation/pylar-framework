"""Console commands for the queue layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from pylar.console.command import Command
from pylar.console.output import Output
from pylar.foundation.container import Container
from pylar.queue.config import QueuesConfig
from pylar.queue.queue import JobQueue
from pylar.queue.record import JobRecord
from pylar.queue.worker import Worker


def attach_per_job_logging(worker: Worker, output: Output) -> None:
    """Wire Horizon-style per-job logging onto *worker*.

    Shared between :class:`QueueWorkCommand` (one worker) and
    :class:`QueueSupervisorCommand` (a pool of workers spawned on the
    fly) so a single function controls the line format. Each hook
    fires on its corresponding :class:`Worker` event and prints one
    line per lifecycle transition with the queue name surfaced after
    the job class — operators watching a supervisor log can tell at a
    glance which queue is doing what.
    """

    def _ts() -> str:
        return datetime.now(UTC).strftime("%H:%M:%S")

    def _label(record: JobRecord) -> str:
        return f"{record.job_class} on {record.queue} (id={record.id})"

    def _on_processing(record: JobRecord) -> None:
        output.info(f"[{_ts()}] Processing   {_label(record)}")

    def _on_processed(record: JobRecord, elapsed: float) -> None:
        output.success(
            f"[{_ts()}] Processed    {_label(record)} ({elapsed:.2f}s)",
        )

    def _on_failed(
        record: JobRecord, elapsed: float, exc: BaseException,
    ) -> None:
        output.warn(
            f"[{_ts()}] Failed       {_label(record)} "
            f"({elapsed:.2f}s) — {type(exc).__name__}: {exc}",
        )

    worker.on_processing(_on_processing)
    worker.on_processed(_on_processed)
    worker.on_failed(_on_failed)


@dataclass(frozen=True)
class QueueWorkInput:
    once: bool = field(
        default=False,
        metadata={"help": "Process a single job and exit"},
    )
    timeout: int = field(
        default=1,
        metadata={"help": "Seconds to wait for a job before re-checking the stop flag"},
    )
    concurrency: int = field(
        default=1,
        metadata={"help": "Number of in-flight job slots (default: 1)"},
    )
    queue: str = field(
        default="default",
        metadata={"help": "Comma-separated priority list (e.g. high,default,low)"},
    )


class QueueWorkCommand(Command[QueueWorkInput]):
    name = "queue:work"
    description = "Process queued jobs until interrupted"
    input_type = QueueWorkInput

    def __init__(self, worker: Worker, output: Output) -> None:
        self.worker = worker
        self.out = output

    async def handle(self, input: QueueWorkInput) -> int:
        if input.concurrency > 1:
            self.worker._concurrency = input.concurrency
        self.worker.listen_on(_parse_queues(input.queue))

        # Horizon-style per-job lines so the operator sees what the
        # worker is doing in real time rather than a silent log with
        # the occasional "Processed N jobs." summary.
        attach_per_job_logging(self.worker, self.out)

        if input.once:
            ran = await self.worker.process_next(timeout=float(input.timeout))
            if not ran:
                self.out.info("No job available.")
            return 0

        self._print_startup_banner(input)
        try:
            await self.worker.run(timeout=float(input.timeout))
        except KeyboardInterrupt:
            self.worker.stop()
        self.out.newline()
        self.out.info("Worker stopped.")
        return 0

    def _print_startup_banner(self, input: QueueWorkInput) -> None:
        slots = self.worker._concurrency
        driver = type(self.worker._queue).__name__
        self.out.definitions([
            ("Driver", driver),
            ("Queues", ", ".join(self.worker.queues)),
            ("Concurrency", f"{slots} slot{'s' if slots != 1 else ''}"),
            ("Poll timeout", f"{input.timeout}s"),
        ])
        self.out.newline()
        self.out.success(
            "Worker ready — processing jobs. Press Ctrl-C to stop."
        )


# --------------------------------------------------------- queue:supervisor


@dataclass(frozen=True)
class _QueueSupervisorInput:
    poll: float = field(
        default=1.0,
        metadata={"help": "Seconds between scaling decisions (default: 1.0)"},
    )


class QueueSupervisorCommand(Command[_QueueSupervisorInput]):
    """``pylar queue:supervisor`` — autoscaling pool across every queue.

    Spawns workers per queue based on :class:`QueueConfig.min_workers`
    / ``max_workers`` from :class:`QueuesConfig`, then scales up/down
    by polling :meth:`JobQueue.size` against the queue's
    ``scale_threshold`` and ``scale_cooldown_seconds``. Designed as a
    long-running container process — receive SIGTERM/SIGINT to drain
    cleanly.
    """

    name = "queue:supervisor"
    description = "Run the autoscaling worker supervisor across every queue"
    input_type = _QueueSupervisorInput

    def __init__(
        self,
        queue: JobQueue,
        queues_config: QueuesConfig,
        container: Container,
        output: Output,
    ) -> None:
        self.queue = queue
        self.queues_config = queues_config
        self.container = container
        self.out = output

    async def handle(self, input: _QueueSupervisorInput) -> int:
        import asyncio
        import signal

        from pylar.queue.supervisor import QueueSupervisor

        # Hook Horizon-style per-job log lines onto every worker the
        # supervisor spawns — same format ``queue:work`` emits, so
        # operators see a consistent stream regardless of which
        # command is running.
        def _wire(worker: Worker, _queue: str) -> None:
            attach_per_job_logging(worker, self.out)

        def _on_scale(
            queue_name: str, before: int, after: int, reason: str,
        ) -> None:
            ts = datetime.now(UTC).strftime("%H:%M:%S")
            arrow = "↑" if after > before else "↓"
            line = (
                f"[{ts}] Scaled {arrow} {queue_name}: "
                f"{before} → {after} workers ({reason})"
            )
            if after > before:
                self.out.success(line)
            else:
                self.out.info(line)

        supervisor = QueueSupervisor(
            self.queue,
            self.container,
            self.queues_config,
            poll_seconds=input.poll,
            on_worker_spawn=_wire,
            on_scale=_on_scale,
        )

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, supervisor.stop)
            except NotImplementedError:
                pass  # Windows

        self._print_startup_banner()
        try:
            await supervisor.run()
        except KeyboardInterrupt:
            supervisor.stop()
        self.out.newline()
        self.out.info("Supervisor stopped.")
        return 0

    def _print_startup_banner(self) -> None:
        rows: list[tuple[str, ...]] = []
        for name, cfg in self.queues_config.queues.items():
            rows.append((
                name,
                f"{cfg.min_workers}-{cfg.max_workers}",
                f"≥{cfg.scale_threshold}",
                f"{cfg.scale_cooldown_seconds}s",
                f"{cfg.tries}",
                f"{cfg.timeout}s",
            ))
        self.out.table(
            headers=("Queue", "Workers", "Scale up at", "Cooldown", "Tries", "Timeout"),
            rows=rows,
            title="Queue Supervisor",
        )
        self.out.newline()
        self.out.success(
            "Supervisor ready - autoscaling workers. Press Ctrl-C to stop."
        )


# ----------------------------------------------------------- queue:failed


@dataclass(frozen=True)
class _QueueFailedInput:
    """No arguments — prints every record currently in the failed pool."""


class QueueFailedCommand(Command[_QueueFailedInput]):
    """``pylar queue:failed`` — list every record that exhausted its retries."""

    name = "queue:failed"
    description = "List jobs that exhausted their retries and live in the failed pool"
    input_type = _QueueFailedInput

    def __init__(self, queue: JobQueue, output: Output) -> None:
        self.queue = queue
        self.out = output

    async def handle(self, input: _QueueFailedInput) -> int:
        failed = await self.queue.failed_records()
        if not failed:
            self.out.info("No failed jobs.")
            return 0
        rows: list[tuple[str, ...]] = [
            (
                entry.record.id,
                entry.record.job_class,
                str(entry.record.attempts),
                entry.error,
            )
            for entry in failed
        ]
        self.out.table(
            headers=("ID", "Job", "Attempts", "Error"),
            rows=rows,
            title="Failed Jobs",
        )
        self.out.newline()
        self.out.warn(f"{len(failed)} failed job(s).")
        return 0


# ------------------------------------------------------------ queue:retry


@dataclass(frozen=True)
class QueueRetryInput:
    record_id: str = field(
        default="",
        metadata={"help": "Specific failed record id to re-queue (default: all)"},
    )


class QueueRetryCommand(Command[QueueRetryInput]):
    """``pylar queue:retry`` — re-queue failed jobs.

    Without arguments, every failed record is moved back into the
    main queue. Pass a record id to re-queue exactly one.
    """

    name = "queue:retry"
    description = "Move failed jobs back into the main queue"
    input_type = QueueRetryInput

    def __init__(self, queue: JobQueue, output: Output) -> None:
        self.queue = queue
        self.out = output

    async def handle(self, input: QueueRetryInput) -> int:
        target = input.record_id or None
        moved = await self.queue.retry_failed(target)
        if moved == 0:
            self.out.info("No matching failed jobs to retry.")
            return 0
        self.out.success(f"Re-queued {moved} job(s).")
        return 0


# ------------------------------------------------------------ queue:run


@dataclass(frozen=True)
class _QueueRunInput:
    timeout: int = field(
        default=1,
        metadata={"help": "Seconds to wait for a job before giving up"},
    )
    queue: str = field(
        default="default",
        metadata={"help": "Comma-separated priority list (e.g. high,default,low)"},
    )


class QueueRunCommand(Command[_QueueRunInput]):
    """``pylar queue:run`` — process one pending job and exit.

    Equivalent to ``queue:work --once`` but as a dedicated one-shot
    command so cron / CI pipelines can drain the queue without
    spawning a long-running worker.
    """

    name = "queue:run"
    description = "Process a single pending job and exit"
    input_type = _QueueRunInput

    def __init__(self, worker: Worker, output: Output) -> None:
        self.worker = worker
        self.out = output

    async def handle(self, input: _QueueRunInput) -> int:
        self.worker.listen_on(_parse_queues(input.queue))
        ran = await self.worker.process_next(timeout=float(input.timeout))
        if ran:
            self.out.success("Processed 1 job.")
        else:
            self.out.info("No job available.")
        return 0


# --------------------------------------------------------- queue:forget


@dataclass(frozen=True)
class _QueueForgetInput:
    record_id: str = field(
        metadata={"help": "Failed job id to delete"},
    )


class QueueForgetCommand(Command[_QueueForgetInput]):
    """``pylar queue:forget <id>`` — delete one failed record."""

    name = "queue:forget"
    description = "Delete a single failed job by id"
    input_type = _QueueForgetInput

    def __init__(self, queue: JobQueue, output: Output) -> None:
        self.queue = queue
        self.out = output

    async def handle(self, input: _QueueForgetInput) -> int:
        removed = await self.queue.forget_failed(input.record_id)
        if not removed:
            self.out.error(f"No failed job with id {input.record_id!r}.")
            return 1
        self.out.success(f"Deleted failed job {input.record_id}.")
        return 0


# ---------------------------------------------------------- queue:flush


@dataclass(frozen=True)
class _QueueFlushInput:
    force: bool = field(
        default=False,
        metadata={"help": "Skip interactive confirmation"},
    )


class QueueFlushCommand(Command[_QueueFlushInput]):
    """``pylar queue:flush`` — delete every record in the failed pool."""

    name = "queue:flush"
    description = "Delete every failed job from the failed pool"
    input_type = _QueueFlushInput

    def __init__(self, queue: JobQueue, output: Output) -> None:
        self.queue = queue
        self.out = output

    async def handle(self, input: _QueueFlushInput) -> int:
        if not input.force:
            self.out.warn("This will delete every failed job.")
            if not self.out.confirm("Do you really wish to run this command?"):
                self.out.info("Command cancelled.")
                return 1
        count = await self.queue.flush_failed()
        self.out.success(f"Flushed {count} failed job(s).")
        return 0


# ---------------------------------------------------------- queue:clear


@dataclass(frozen=True)
class _QueueClearInput:
    force: bool = field(
        default=False,
        metadata={"help": "Skip interactive confirmation"},
    )


class QueueClearCommand(Command[_QueueClearInput]):
    """``pylar queue:clear`` — drop every pending job from the queue."""

    name = "queue:clear"
    description = "Delete every pending job from the main queue"
    input_type = _QueueClearInput

    def __init__(self, queue: JobQueue, output: Output) -> None:
        self.queue = queue
        self.out = output

    async def handle(self, input: _QueueClearInput) -> int:
        if not input.force:
            self.out.warn("This will delete every pending job in the queue.")
            if not self.out.confirm("Do you really wish to run this command?"):
                self.out.info("Command cancelled.")
                return 1
        count = await self.queue.clear_pending()
        self.out.success(f"Cleared {count} pending job(s).")
        return 0


# ---------------------------------------------------- queue:prune-failed


@dataclass(frozen=True)
class _QueuePruneFailedInput:
    hours: int = field(
        default=24,
        metadata={"help": "Drop failed jobs older than this many hours (default: 24)"},
    )


class QueuePruneFailedCommand(Command[_QueuePruneFailedInput]):
    """``pylar queue:prune-failed`` — drop old failed records.

    Mirrors ``php artisan queue:prune-failed``: removes every record
    in the failed pool whose ``failed_at`` is older than ``--hours``.
    Designed to run on a daily schedule.
    """

    name = "queue:prune-failed"
    description = "Drop failed jobs older than the given age"
    input_type = _QueuePruneFailedInput

    def __init__(self, queue: JobQueue, output: Output) -> None:
        self.queue = queue
        self.out = output

    async def handle(self, input: _QueuePruneFailedInput) -> int:
        cutoff = datetime.now(UTC) - timedelta(hours=input.hours)
        count = await self.queue.prune_failed(cutoff)
        self.out.success(
            f"Pruned {count} failed job(s) older than {input.hours}h."
        )
        return 0


def _parse_queues(spec: str) -> tuple[str, ...]:
    """Split ``--queue=high,default,low`` into a priority tuple.

    Whitespace around names is stripped and empty entries are dropped
    so ``"high, ,low"`` collapses to ``("high", "low")``. An empty
    spec falls back to ``("default",)`` — matches Laravel's behaviour
    when ``--queue`` is omitted.
    """
    parts = tuple(part.strip() for part in spec.split(",") if part.strip())
    return parts or ("default",)
