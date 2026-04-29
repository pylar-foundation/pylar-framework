# queue/ — backlog

## ~~Persistent drivers~~ ✓

`DatabaseQueue`, `RedisQueue` both shipped.

## ~~Job middleware~~ ✓

`JobMiddleware` base + `WithoutOverlapping`, `RateLimited`, `Throttled`.

## ~~Worker concurrency~~ ✓

`Worker(concurrency=N)` + `--concurrency` CLI flag.

## ~~`retry_until` deadline~~ ✓

`Job.retry_until: timedelta | None`.

## ~~Named queues + priorities~~ ✓ (ADR-0006)

`JobRecord.queue`, `Job.queue` ClassVar, `queue=` dispatch override,
`pop(queues=(...))` priority-ordered, `Job.tries`/`timeout`/`backoff`
ClassVar overrides, `QueueConfig` + `QueuesConfig` per-queue policy,
`DEFAULT_QUEUES` for high/default/low.

## ~~Queue lifecycle commands~~ ✓

`queue:run`, `queue:forget`, `queue:flush`, `queue:clear`,
`queue:prune-failed`, `queue:supervisor`.

## ~~QueueSupervisor (autoscaling)~~ ✓ (ADR-0006 phase 3)

Autoscaling pool across named queues: min/max workers, scale by
backlog depth, per-queue cooldown.

## Still on the wishlist

### SQS driver

Optional dep behind `pylar[queue-sqs]`.

### Queue monitoring UI

Horizon-like web dashboard — potential `pylar-horizon` package.
