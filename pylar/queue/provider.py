"""Service provider that wires the queue layer."""

from __future__ import annotations

from pylar.console.kernel import COMMANDS_TAG
from pylar.foundation.container import Container
from pylar.foundation.provider import ServiceProvider
from pylar.queue.commands import (
    QueueClearCommand,
    QueueFailedCommand,
    QueueFlushCommand,
    QueueForgetCommand,
    QueuePruneFailedCommand,
    QueueRetryCommand,
    QueueRunCommand,
    QueueSupervisorCommand,
    QueueWorkCommand,
)
from pylar.queue.config import QueuesConfig
from pylar.queue.dispatcher import Dispatcher
from pylar.queue.drivers.memory import MemoryQueue
from pylar.queue.queue import JobQueue
from pylar.queue.worker import Worker


class QueueServiceProvider(ServiceProvider):
    """Bind a default in-memory queue, dispatcher, worker, and commands.

    Production deployments override the :class:`JobQueue` binding in
    their own service provider — for example pointing it at a
    database-backed driver — and pylar's dispatcher, worker, and
    queue:* commands pick up the change without further wiring.

    Tagged commands: ``queue:work``, ``queue:failed``, ``queue:retry``.
    """

    def register(self, container: Container) -> None:
        if not container.has(QueuesConfig):
            container.instance(QueuesConfig, QueuesConfig())
        container.singleton(JobQueue, MemoryQueue)  # type: ignore[type-abstract]
        container.singleton(Dispatcher, self._make_dispatcher)
        container.singleton(Worker, self._make_worker)
        container.tag(
            [
                QueueWorkCommand,
                QueueRunCommand,
                QueueSupervisorCommand,
                QueueFailedCommand,
                QueueRetryCommand,
                QueueForgetCommand,
                QueueFlushCommand,
                QueueClearCommand,
                QueuePruneFailedCommand,
            ],
            COMMANDS_TAG,
        )

    def _make_dispatcher(self) -> Dispatcher:
        queue = self.app.container.make(JobQueue)  # type: ignore[type-abstract]
        return Dispatcher(queue)

    def _make_worker(self) -> Worker:
        queue = self.app.container.make(JobQueue)  # type: ignore[type-abstract]
        return Worker(queue, self.app.container)
