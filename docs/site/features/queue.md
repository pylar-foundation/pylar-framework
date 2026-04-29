# Queue & Jobs

Pylar's queue module provides typed, async background job processing with retries, backoff, middleware, and a built-in worker.

## Defining a Job

Every job has a typed payload (a frozen Pydantic model) and a `handle` method:

```python
from pylar.queue import Job, JobPayload

class SendWelcomePayload(JobPayload):
    user_id: int
    email: str

class SendWelcomeJob(Job[SendWelcomePayload]):
    payload_type = SendWelcomePayload
    max_attempts = 3
    backoff = (10, 60, 300)  # seconds between retries

    async def handle(self, payload: SendWelcomePayload) -> None:
        user = await User.objects.find(payload.user_id)
        await mailer.send(WelcomeMailable(user))
```

## Dispatching Jobs

```python
from pylar.queue import Dispatcher

dispatcher: Dispatcher  # auto-wired

await dispatcher.dispatch(SendWelcomeJob, SendWelcomePayload(user_id=42, email="a@b.com"))

# Delayed dispatch:
from datetime import timedelta
await dispatcher.dispatch(SendWelcomeJob, payload, delay=timedelta(minutes=5))
```

## Retry & Backoff

| Option | Type | Description |
|---|---|---|
| `max_attempts` | `int` | Maximum execution attempts (default 1 = no retry) |
| `backoff` | `tuple[int, ...]` | Delay in seconds for each retry. Last value repeats. |
| `retry_until` | `timedelta \| None` | Absolute timeout — stop retrying after this duration |

## Job Middleware

Wrap job execution with reusable logic:

```python
from pylar.queue import Job, WithoutOverlapping, RateLimited

class ImportCsvJob(Job[ImportPayload]):
    payload_type = ImportPayload
    middleware = (WithoutOverlapping, RateLimited)

    async def handle(self, payload: ImportPayload) -> None: ...
```

Built-in middleware:

| Middleware | Behavior |
|---|---|
| `WithoutOverlapping` | Cache lock prevents concurrent execution of same job class |
| `RateLimited` | Counter-based rate limiting per time window |
| `Throttled` | Cooldown when upstream returns rate-limit errors |

## Running the Worker

```bash
pylar queue:work
```

The worker pulls jobs from the queue, resolves the job class from the container, and executes with full retry/backoff support. Handles `SIGTERM`/`SIGINT` for graceful shutdown.

```python
from pylar.queue import Worker

worker = Worker(queue, container, concurrency=4)
await worker.run()
```

## Failed Jobs

Jobs that exhaust all retry attempts are recorded as failed:

```python
failed = await queue.failed_records()  # list[FailedJob]

# Retry all failed jobs:
retried = await queue.retry_failed()

# Retry a specific job:
await queue.retry_failed(record_id="abc-123")
```

## Recent-jobs history

The driver keeps a short ring of terminal records so the admin panel
(and anything else calling `recent_records`) can show what just
happened — completed, failed, and cancelled jobs all land in the same
pool so operators see a single Horizon-style timeline regardless of
outcome.

```python
from pylar.queue.queue import RecentJob  # status: "completed" | "failed" | "cancelled"

history: list[RecentJob] = await queue.recent_records("default")
for entry in history:
    print(entry.record.job_class, entry.status, entry.completed_at, entry.error)
```

The worker calls `record_completed(record, status=..., error=...)`
automatically on every terminal transition — successful ack, final
failure, and the admin cancel flow. Each driver enforces its own TTL
(`recent_retention_seconds=3600` by default on `MemoryQueue` and
`RedisQueue`) so the pool stays bounded; records older than the
retention window are pruned on every read.

| Driver | Recent history |
|---|---|
| `MemoryQueue` | In-process ring per queue, TTL-pruned on read |
| `RedisQueue` | Sorted set per queue, TTL-pruned on read |
| `DatabaseQueue` | No-op (returns `[]`) — no ring table by design |
| `SqsQueue` | No-op — SQS has no retention surface |

## Pagination

The admin-facing read methods accept `limit` / `offset` so callers can
page through deep backlogs without loading everything at once:

```python
page = await queue.pending_records("default", limit=50, offset=100)
recent = await queue.recent_records("default", limit=50, offset=0)

pending_total = await queue.size("default")
recent_total = await queue.recent_size("default")
```

`size` and `recent_size` give the totals you need for the pagination
meta. Drivers that cannot enumerate (SQS) keep returning an empty
page — that is a valid answer in the contract.

## Supervisor & autoscaling

`QueueSupervisor` is the long-running orchestrator: one process
spawns and reaps workers per named queue based on the matching
`QueueConfig` policy and scales the pool against backlog depth.

```python
from pylar.queue import QueueSupervisor
from pylar.queue.commands import attach_per_job_logging

def wire(worker, queue_name):
    attach_per_job_logging(worker, output)

def announce(queue_name, before, after, reason):
    output.info(f"Scaled {queue_name}: {before} -> {after} ({reason})")

supervisor = QueueSupervisor(
    queue,
    container,
    queues_config,
    on_worker_spawn=wire,
    on_scale=announce,
)
await supervisor.run()
```

Both hooks are optional:

- `on_worker_spawn: Callable[[Worker, str], None]` — invoked once per
  spawned worker with the `(worker, queue_name)` pair. Use it to wire
  `on_processing` / `on_processed` / `on_failed` hooks onto each new
  worker so the supervisor's log stream matches the one `queue:work`
  produces.
- `on_scale: Callable[[str, int, int, str], None]` — invoked when a
  pool's worker count changes. Args are
  `(queue_name, before, after, reason)` where `reason` is one of
  `"startup"`, `"depth=N"`, `"idle"`, or `"floor"` so operators can
  tell *why* the pool just grew or shrunk.

The `queue:supervisor` command wires both hooks by default, so the
CLI emits the same per-job lines as `queue:work` plus a
`Scaled up low: 1 → 2 (depth=55)` line whenever the supervisor
reconciles a pool. The helper `attach_per_job_logging(worker, output)`
is exported from `pylar.queue.commands` — reach for it when you embed
the supervisor (or a plain `Worker`) in your own entrypoint and want
the same Horizon-style output.

## Live worker counts

On every tick the supervisor publishes its current worker count per
queue through `report_worker_count(queue, count, *, ttl_seconds=30)`
so the admin panel can render the live pool size. The admin (or any
other consumer) reads the snapshot back via `worker_counts()`:

```python
counts: dict[str, int] = await queue.worker_counts()
# e.g. {"default": 3, "high": 1}
```

| Driver | Surface |
|---|---|
| `RedisQueue` | TTL'd keys at `{prefix}:workers:{queue}`; `SCAN` + `MGET` on read |
| `MemoryQueue` | In-process dict with per-queue deadlines — single-process only |
| `DatabaseQueue` | No-op, returns `{}` |
| `SqsQueue` | No-op, returns `{}` |

The TTL means a supervisor that crashes stops contributing within a
few seconds — the admin then shows 0 rather than a frozen snapshot.

## JobQueue Protocol

Implement this to add a custom backend (Redis, RabbitMQ, etc.):

```python
from pylar.queue import JobQueue

class RedisQueue:
    async def push(self, record: JobRecord) -> None: ...
    async def pop(self, *, timeout: float = 1.0) -> JobRecord | None: ...
    async def ack(self, record: JobRecord) -> None: ...
    async def fail(self, record: JobRecord, error: str) -> None: ...
```

## Testing

Use `FakeDispatcher` to assert jobs were dispatched without running them:

```python
from pylar.queue import Dispatcher

fake = Dispatcher.fake()

await fake.dispatch(SendWelcomeJob, payload)

fake.assert_dispatched(SendWelcomeJob, times=1)
fake.assert_not_dispatched(ImportCsvJob)
dispatched = fake.dispatched(SendWelcomeJob)  # list[JobPayload]
```

## Built-in Queue

| Queue | Backend | Use Case |
|---|---|---|
| `MemoryQueue` | Heap-based in-process | Development, testing |
