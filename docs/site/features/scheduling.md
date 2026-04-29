# Scheduling

Pylar's scheduling layer lets you define recurring tasks in Python code instead of scattering cron entries across your server. A single system cron entry runs `pylar schedule:run` every minute, and pylar decides which tasks are due.

## Defining a schedule

Register tasks inside a service provider's `boot()` method by resolving the `Schedule` singleton from the container:

```python
from pylar.scheduling import Schedule
from pylar.foundation import ServiceProvider


class TaskServiceProvider(ServiceProvider):
    async def boot(self) -> None:
        schedule = self.app.container.make(Schedule)

        schedule.command("cache:clear").daily_at("02:00").name("nightly-cache-clear")

        schedule.call(send_daily_digest).daily_at("08:00").timezone("America/New_York")

        schedule.job(GenerateReportJob, ReportPayload(format="pdf")).weekly_on(1, "06:00")
```

## Task types

### CommandTask

Runs a registered console command by name. Arguments are passed as a sequence of strings:

```python
schedule.command("migrate:status", args=["--verbose"]).hourly()
```

### CallableTask

Wraps any `async def` callable that takes no arguments:

```python
async def ping_health_check() -> None:
    ...

schedule.call(ping_health_check).every_five_minutes()
```

### JobTask

Dispatches a queue job with a payload. The job runs on a worker, not inline, so a missed tick still gets retried through the queue's failure policy:

```python
from app.jobs.cleanup import CleanupJob, CleanupPayload

schedule.job(CleanupJob, CleanupPayload(max_age_days=30)).daily()
```

## Fluent frequency builder

Every `schedule.command()`, `schedule.call()`, and `schedule.job()` call returns a `ScheduledTaskBuilder` with these chainable methods:

| Method | Cron equivalent |
|---|---|
| `.every_minute()` | `* * * * *` |
| `.every_five_minutes()` | `*/5 * * * *` |
| `.every_ten_minutes()` | `*/10 * * * *` |
| `.hourly()` | `0 * * * *` |
| `.hourly_at(15)` | `15 * * * *` |
| `.daily()` | `0 0 * * *` |
| `.daily_at("14:30")` | `30 14 * * *` |
| `.weekly()` | `0 0 * * 0` |
| `.weekly_on(3, "09:00")` | `0 9 * * 3` |
| `.monthly()` | `0 0 1 * *` |
| `.cron("5 4 * * 1-5")` | any valid expression |

Additional options:

```python
schedule.command("reports:send") \
    .daily_at("03:00") \
    .timezone("Europe/Berlin") \
    .without_overlapping(ttl=300) \
    .name("daily-reports")
```

`.without_overlapping()` acquires a cache lock before running so a slow task does not spawn a second copy on the next tick. `.on_one_server()` is sugar for the same mechanism with a longer default TTL, intended for cluster-wide singletons backed by a shared cache store.

## Running the scheduler

Add one system cron entry:

```
* * * * * cd /path/to/project && pylar schedule:run >> /dev/null 2>&1
```

## Listing tasks

```
$ pylar schedule:list
  0 0 * * *    2026-04-13 00:00 UTC  nightly-cache-clear
  0 8 * * *    2026-04-12 08:00 EDT  call send_daily_digest
  0 6 * * 1    2026-04-13 06:00 UTC  job GenerateReportJob
```

The `schedule:list` command prints every registered task with its cron expression and the next calculated fire time.
