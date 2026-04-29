"""Console commands for the cache layer."""

from __future__ import annotations

from dataclasses import dataclass

from pylar.cache.cache import Cache
from pylar.console.command import Command
from pylar.console.output import Output


@dataclass(frozen=True)
class CacheClearInput:
    """No arguments — flushes the entire cache store."""


class CacheClearCommand(Command[CacheClearInput]):
    """Flush every key from the application cache.

    Delegates to :meth:`Cache.flush` which clears the underlying store
    (memory, file, Redis, database) and resets the tag index.
    """

    name = "cache:clear"
    description = "Flush the entire application cache"
    input_type = CacheClearInput

    def __init__(self, cache: Cache, output: Output) -> None:
        self._cache = cache
        self.out = output

    async def handle(self, input: CacheClearInput) -> int:
        await self._cache.flush()
        self.out.success("Application cache flushed.")
        return 0
