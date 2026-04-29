"""Distributed locks built on top of the cache layer.

A :class:`CacheLock` uses an atomic ``add``-if-absent to claim a key
with a unique **owner token**. Only the coroutine that holds the token
can release the lock — this prevents a slow task from accidentally
releasing a lock that has already been claimed by a different worker
after the TTL expired and a new acquirer took over.

The lock is **best-effort distributed**: when the cache backend is a
single-process :class:`MemoryCacheStore` it serialises coroutines
inside the same process. When the user binds Redis or a database the
same code coordinates across the entire cluster.

Usage::

    async with cache.lock("billing:user:42", ttl=30):
        await charge_card(user)
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING
from uuid import uuid4

from pylar.cache.exceptions import CacheLockError

if TYPE_CHECKING:
    from pylar.cache.cache import Cache


class CacheLock:
    """A best-effort distributed lock with owner verification."""

    def __init__(
        self,
        cache: Cache,
        key: str,
        *,
        ttl: int = 60,
        retry_seconds: float = 0.1,
    ) -> None:
        self._cache = cache
        self._key = key
        self._ttl = ttl
        self._retry_seconds = retry_seconds
        self._held = False
        #: Unique token generated for this lock instance. The token is
        #: stored in the cache as the lock value so :meth:`release` can
        #: verify it still owns the key before deleting.
        self._token = uuid4().hex

    @property
    def key(self) -> str:
        return self._key

    @property
    def held(self) -> bool:
        return self._held

    async def acquire(
        self,
        *,
        blocking: bool = True,
        timeout: float | None = None,
    ) -> bool:
        """Try to claim the lock.

        With ``blocking=True`` (default) the call waits until the lock
        becomes available or *timeout* seconds elapse, raising
        :class:`CacheLockError` on timeout. With ``blocking=False`` the
        call returns immediately: ``True`` on success, ``False`` if the
        lock is currently held by someone else.
        """
        deadline: float | None = (
            time.monotonic() + timeout if timeout is not None else None
        )
        while True:
            acquired = await self._cache.add(
                self._key, self._token, ttl=self._ttl
            )
            if acquired:
                self._held = True
                return True
            if not blocking:
                return False
            if deadline is not None and time.monotonic() >= deadline:
                raise CacheLockError(
                    f"Could not acquire cache lock {self._key!r} within {timeout}s"
                )
            await asyncio.sleep(self._retry_seconds)

    async def release(self) -> None:
        """Release the lock only if this instance still owns it.

        If the TTL has expired and another acquirer has taken over,
        the release is a no-op — the current owner's token no longer
        matches the stored value, so the other acquirer's lock stays
        intact.
        """
        if not self._held:
            return
        current = await self._cache.get(self._key)
        if current == self._token:
            await self._cache.forget(self._key)
        self._held = False

    async def __aenter__(self) -> CacheLock:
        await self.acquire()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.release()
