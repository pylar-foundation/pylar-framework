# ADR-0006: Named queues, priorities, per-queue config, supervised workers

## Status

Accepted. Supersedes the single-queue model implicit in the original
`pylar/queue/` design (ADR-0001 / ADR-0003).

## Context

Until now the queue layer treated every dispatched `Job` as belonging
to one anonymous FIFO. This is enough for a demo but every real
application needs to:

* Dispatch latency-sensitive work (password reset emails) ahead of
  bulk work (nightly digest rebuild) — i.e. **priorities**.
* Tune retry / timeout policy per kind of work — short HTTP calls
  retry quickly, long video transcodes get a generous timeout.
* Run several workers in parallel, with **autoscaling** between a
  configured minimum and maximum based on backlog depth — without
  a sidecar daemon like Horizon.

Laravel's queue / Horizon ecosystem is the reference. We adopt its
ergonomics where they fit a typed, async-first Python framework and
diverge where blindly copying would fight Python's concurrency
primitives.

## Decision

### 1. Named queues

Every job ships with a string queue name. The wire format gains a
`JobRecord.queue: str = "default"` field. Three queues are conceptual
defaults — `high`, `default`, `low` — but the system is open: any
string is a valid queue name and drivers create buckets on demand.

```python
class SendWelcomeJob(Job[SendWelcomePayload]):
    queue = "high"  # ClassVar override on the Job subclass
    payload_type = SendWelcomePayload
```

Dispatch-time override beats the class default:

```python
await dispatcher.dispatch(SendWelcomeJob, payload, queue="low")
```

### 2. Priority pop

The `JobQueue` protocol replaces single-queue `pop(*, timeout)` with
`pop(*, queues=("default",), timeout)` that walks the tuple in
**declared order** and returns the first available record. There is
no fairness pass — a queue earlier in the list is always preferred,
matching Laravel's `--queue=high,default,low` semantics.

Each driver stores records in per-queue buckets so this is O(1):

* `MemoryQueue` — a `dict[str, list]` keyed by queue name.
* `DatabaseQueue` — adds a `queue` column to `pylar_jobs` and
  `pylar_failed_jobs`, indexed for the priority-ordered SELECT.
* `RedisQueue` — one Redis list per queue (`pylar:queue:<name>`).

### 3. Worker listens to a list of queues

`Worker` and the `queue:work` command accept a queue priority list:

```bash
pylar queue:work --queue=high,default,low
```

A single worker process drains the list in order. We do **not** model
"shared" vs "dedicated" workers (Laravel doesn't either) — operators
get the same effect by running multiple `queue:work` invocations with
different `--queue` lists.

### 4. Per-queue config

A new `QueueConfig` dataclass lives in `pylar/queue/config.py`:

```python
@dataclass(frozen=True)
class QueueConfig:
    tries: int = 1
    timeout: int = 60                 # seconds
    backoff: tuple[int, ...] = ()
    min_workers: int = 1
    max_workers: int = 1
    scale_threshold: int = 50         # autoscale up when backlog ≥ this
    scale_cooldown_seconds: int = 30  # min gap between scaling decisions
```

Applications declare a mapping in `config/queue.py`:

```python
QUEUES = {
    "high":    QueueConfig(tries=5, timeout=30, min_workers=2, max_workers=10),
    "default": QueueConfig(tries=3, timeout=60),
    "low":     QueueConfig(tries=1, timeout=300, max_workers=1),
}
```

Job classes may still pin their own retry / backoff / timeout
(`Job.max_attempts`, `Job.backoff`) — those override the queue defaults
on a per-class basis, matching Laravel's `public $tries = 5` semantics.

### 5. Supervised workers + autoscaling (Phase 3)

`QueueSupervisor` is a long-running process that spawns and reaps
`Worker` instances per queue using `min_workers` / `max_workers` from
`QueueConfig`. The supervisor polls `JobQueue.size(queue)` every
`scale_cooldown_seconds` and scales:

* up: backlog ≥ `scale_threshold` and current count < `max_workers`
* down: backlog == 0 for one full cooldown window and current count >
  `min_workers`

The supervisor is exposed as `pylar queue:supervisor`. Single-queue
direct invocation via `queue:work` is preserved for ad-hoc operator
use, debugging, and CI drains.

### 6. Phasing

We ship this in three commits:

* **Phase 1** — named queues + priority pop + `queue:work --queue=…`.
  Drivers migrate to per-queue buckets. No autoscaling yet.
* **Phase 2** — `QueueConfig`, `Job` overrides, `config/queue.py`
  loader, retry / timeout policy honours queue config.
* **Phase 3** — `QueueSupervisor` + `queue:supervisor` command +
  `JobQueue.size(queue)` for autoscaling decisions.

Each phase ships green: tests cover the new surface, mypy stays
clean, the example blog continues to work without changes (defaults
preserve current behaviour).

## Consequences

* **Migration**: the `DatabaseQueue` driver creates its own tables
  via `bootstrap()` (`Metadata.create_all` is idempotent for new
  tables but doesn't add columns to existing ones). Apps that already
  have `pylar_jobs` / `pylar_failed_jobs` rows must hand-add a
  `queue VARCHAR(64) NOT NULL DEFAULT 'default'` column on each
  table — there is no application-owned migration since these tables
  belong to the framework. In-memory and Redis drivers have no
  migration cost.
* **Backwards compatibility**: `Dispatcher.dispatch(Job, payload)` and
  `JobQueue.pop(timeout=…)` keep working — the queue argument
  defaults to `"default"` and `queues` defaults to `("default",)`.
  Existing apps see no behaviour change.
* **Scope**: we deliberately **do not** ship metrics, a UI, or a
  separate web dashboard. Horizon's value proposition is mostly the
  observability layer; the framework's job is to give applications
  the primitives. A `pylar-horizon` package can layer a UI later.
