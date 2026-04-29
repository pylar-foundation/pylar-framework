"""Kernel protocol — the entry point that drives a bootstrapped application."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Kernel(Protocol):
    """A run mode for the application: HTTP server, console command, queue worker, ..."""

    async def handle(self) -> int:
        """Run the kernel and return a process exit code."""
        ...
