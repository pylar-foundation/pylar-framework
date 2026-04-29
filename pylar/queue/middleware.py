"""Reusable :class:`JobMiddleware` implementations.

The bundled middlewares cover the cross-cutting concerns most queues
end up needing: rate limiting per logical key, distributed overlap
protection so two workers cannot run the same logical task at once,
and external-throttle backoff that pauses retries when an upstream
API is over its limit. Each middleware is opt-in — a job declares
``middleware = (RateLimited, ...)`` and the worker composes the chain
around :meth:`Job.handle`.

All middlewares depend on :class:`pylar.cache.Cache` for cross-process
state. Subclasses are constructed by the container, so they receive
the cache through their typed ``__init__``.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any, ClassVar

from pylar.cache.cache import Cache
from pylar.cache.exceptions import CacheLockError
from pylar.queue.job import Job, JobMiddleware, JobMiddlewareNext
from pylar.queue.payload import JobPayload


class WithoutOverlapping(JobMiddleware):
    """Acquire a distributed lock around the job body.

    Two workers running the same job class concurrently — say a nightly
    report generator that fires from cron and from a UI button at the
    same time — would normally race. This middleware claims a
    :class:`pylar.cache.CacheLock` keyed by the job class name (override
    via :attr:`lock_key`) before invoking the inner handler. If the
    lock is held the call is silently skipped.

    Configurable knobs (override on the subclass when needed):

    * :attr:`lock_ttl` — how long the lock survives if the worker
      crashes mid-job (default: 5 minutes).
    * :attr:`lock_key_prefix` — namespace for the lock key in cache.
    """

    lock_ttl: ClassVar[int] = 300
    lock_key_prefix: ClassVar[str] = "job-overlap"

    def __init__(self, cache: Cache) -> None:
        self._cache = cache

    async def handle(
        self,
        job: Job[JobPayload],
        payload: JobPayload,
        next_call: JobMiddlewareNext,
    ) -> None:
        key = self._key_for(job)
        lock = self._cache.lock(key, ttl=self.lock_ttl)
        if not await lock.acquire(blocking=False):
            return  # silently skip — the other worker is already handling it
        try:
            await next_call(payload)
        finally:
            await lock.release()

    def _key_for(self, job: Job[Any]) -> str:
        return f"{self.lock_key_prefix}:{type(job).__qualname__}"


class RateLimited(JobMiddleware):
    """At most :attr:`max_calls` invocations per :attr:`window_seconds`.

    Counts execution attempts in a cache key with TTL equal to the
    window. When the counter overflows the call is short-circuited
    (subclass behaviour controls whether to drop or re-queue).

    The default policy *drops* the call so a flood of identical jobs
    cannot stampede past the limit. Override :meth:`on_throttled` to
    requeue with a delay if the work must eventually run.
    """

    max_calls: ClassVar[int] = 60
    window_seconds: ClassVar[int] = 60
    key_prefix: ClassVar[str] = "job-ratelimit"

    def __init__(self, cache: Cache) -> None:
        self._cache = cache

    async def handle(
        self,
        job: Job[JobPayload],
        payload: JobPayload,
        next_call: JobMiddlewareNext,
    ) -> None:
        key = self._key_for(job)
        # Single atomic call — on Redis this is INCRBY + EXPIRE NX in
        # one pipeline, on memory it's mutex-guarded. Passing ``put()``
        # with an int afterwards would double-serialise through pickle
        # and trip up the Redis driver's INCRBY on the next hit.
        try:
            count = await self._cache.increment(
                key, ttl=self.window_seconds,
            )
        except TypeError:
            # Existing key has a non-integer value — bail out rather
            # than corrupt unrelated cache data.
            await next_call(payload)
            return
        if count > self.max_calls:
            await self.on_throttled(job, payload)
            return
        await next_call(payload)

    async def on_throttled(
        self, job: Job[JobPayload], payload: JobPayload
    ) -> None:
        """Hook called when the limit is exceeded.

        Default: drop the call. Override to log or re-queue with a
        delay if the work must run eventually.
        """
        return None

    def _key_for(self, job: Job[Any]) -> str:
        return f"{self.key_prefix}:{type(job).__qualname__}"


class Throttled(JobMiddleware):
    """Back off when an external API has rate-limited us.

    Pairs with the cache layer: when the inner handler raises a
    :class:`ThrottleError` the middleware records a cooldown key in
    cache. Subsequent invocations short-circuit until the cooldown
    expires, sparing the third-party API from a thundering herd.

    Subclass to point at the right exception type and cooldown
    duration::

        class GitHubThrottle(Throttled):
            cooldown_seconds = 60
    """

    cooldown_seconds: ClassVar[int] = 30
    key_prefix: ClassVar[str] = "job-throttle"

    def __init__(self, cache: Cache) -> None:
        self._cache = cache

    async def handle(
        self,
        job: Job[JobPayload],
        payload: JobPayload,
        next_call: JobMiddlewareNext,
    ) -> None:
        key = self._key_for(job)
        if await self._cache.has(key):
            return  # cooldown active
        try:
            await next_call(payload)
        except CacheLockError:
            raise
        except Exception as exc:
            if self._is_throttle(exc):
                await self._cache.put(key, "1", ttl=self.cooldown_seconds)
                return
            raise

    @abstractmethod
    def _is_throttle(self, exc: BaseException) -> bool:
        """Return ``True`` if *exc* indicates a third-party rate limit."""

    def _key_for(self, job: Job[Any]) -> str:
        return f"{self.key_prefix}:{type(job).__qualname__}"
