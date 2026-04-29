# scheduling/ — backlog

The Cache + Scheduling combo landed:

* :meth:`Schedule.job` factory + :class:`JobTask` that dispatches a
  queued :class:`Job` at the configured time. Pairs naturally with
  the queue's retry policy and failed pool — a missed cron tick
  combined with at-least-once delivery still gets the work done.
* ``.without_overlapping(ttl=...)`` on the builder. The schedule
  runner claims a :class:`pylar.cache.CacheLock` before invoking the
  task and silently skips it when the lock is already held by an
  earlier tick. Default lock key is derived from the task name (or
  class), or override with ``key=...``.
* ``.timezone("Europe/Riga")`` evaluates the cron expression in the
  named time zone so a 02:00 daily task runs at 02:00 *local* time
  rather than 02:00 UTC. Time-zone names are parsed through stdlib
  :class:`zoneinfo.ZoneInfo` so a typo dies at provider boot.

What is still on the wishlist:

`SchedulerKernel`, `.on_one_server()`, and the `schedule:list`
next-run column landed:

* :class:`SchedulerKernel` is the long-running in-process loop —
  sleeps in small slices so ``stop()`` is responsive, calls
  ``Schedule.run_due`` once a minute, logs failures and continues.
  Useful for container environments where running a sidecar cron is
  awkward.
* :meth:`ScheduledTaskBuilder.on_one_server` is sugar over
  ``without_overlapping`` with a longer default TTL (1 hour). When
  the bound Cache points at a shared backend the lock makes the
  task cluster-singleton.
* `schedule:list` now prints the next-run timestamp alongside the
  cron expression and the task name.

## Output capture and notifications

`.send_output_to(path)` writes the task's stdout / stderr to a file
in storage. `.email_output_to(...)` notifies on failure. Both belong
to a future "task observability" iteration.
