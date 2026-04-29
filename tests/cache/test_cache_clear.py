"""Tests for the cache:clear command."""

from __future__ import annotations

from io import StringIO

from pylar.cache import Cache, MemoryCacheStore
from pylar.cache.commands import CacheClearCommand, CacheClearInput
from pylar.console.output import Output


class TestCacheClearCommand:
    async def test_flushes_cache(self) -> None:
        store = MemoryCacheStore()
        cache = Cache(store)
        await cache.put("key1", "value1")
        await cache.put("key2", "value2")
        assert await cache.has("key1")

        buf = StringIO()
        cmd = CacheClearCommand(cache, Output(buf, colour=False))
        code = await cmd.handle(CacheClearInput())

        assert code == 0
        assert "flushed" in buf.getvalue()
        assert not await cache.has("key1")
        assert not await cache.has("key2")

    async def test_works_on_empty_cache(self) -> None:
        store = MemoryCacheStore()
        cache = Cache(store)

        buf = StringIO()
        cmd = CacheClearCommand(cache, Output(buf, colour=False))
        code = await cmd.handle(CacheClearInput())

        assert code == 0
        assert "flushed" in buf.getvalue()
