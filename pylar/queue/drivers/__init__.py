"""Concrete :class:`JobQueue` implementations bundled with pylar."""

from pylar.queue.drivers.memory import MemoryQueue

__all__ = ["MemoryQueue"]
