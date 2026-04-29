"""Per-queue configuration — tries, timeout, backoff, worker counts.

Applications declare a mapping from queue name to :class:`QueueConfig`
and bind it into the container via their own service provider or the
bundled :class:`QueueServiceProvider` default. Workers read the
effective policy from the binding at handle time, blended with any
Job-class-level overrides (``Job.tries`` / ``Job.timeout`` /
``Job.backoff``) so operators can tune whole queues without editing
job code and job authors can still pin per-class policy when it
matters.

Laravel-parity mapping:

* ``tries`` ≡ ``public $tries`` on a Laravel Job
* ``timeout`` ≡ ``public $timeout``
* ``backoff`` ≡ ``public $backoff``
* ``min_workers`` / ``max_workers`` ≡ Horizon's
  ``minProcesses`` / ``maxProcesses``
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class QueueConfig:
    """Policy for a single named queue.

    Defaults are conservative: one retry, one-minute timeout, no
    backoff, one dedicated worker. Applications override per queue.
    """

    tries: int = 1
    timeout: int = 60
    backoff: tuple[int, ...] = ()
    min_workers: int = 1
    max_workers: int = 1
    scale_threshold: int = 50
    scale_cooldown_seconds: int = 30


#: Laravel-style defaults for the three built-in queue names. Apps
#: that don't declare their own :class:`QueuesConfig` land here.
DEFAULT_QUEUES: Mapping[str, QueueConfig] = {
    "high": QueueConfig(tries=5, timeout=30, backoff=(1, 5, 10, 30, 60)),
    "default": QueueConfig(tries=3, timeout=60, backoff=(5, 30, 120)),
    "low": QueueConfig(tries=1, timeout=300),
}


@dataclass(frozen=True)
class QueuesConfig:
    """The container-bound mapping of queue name to :class:`QueueConfig`.

    Queues not explicitly declared fall back to :attr:`fallback`,
    which itself defaults to a ``QueueConfig()`` with the dataclass
    defaults. Applications inject a customised instance into the
    container to override the bundled :data:`DEFAULT_QUEUES`::

        container.instance(
            QueuesConfig,
            QueuesConfig(queues={
                "emails":  QueueConfig(tries=5, timeout=30, max_workers=10),
                "default": QueueConfig(tries=3, timeout=60),
            }),
        )
    """

    queues: Mapping[str, QueueConfig] = field(
        default_factory=lambda: dict(DEFAULT_QUEUES)
    )
    fallback: QueueConfig = field(default_factory=QueueConfig)

    def for_queue(self, name: str) -> QueueConfig:
        """Return the config for *name*, or :attr:`fallback` if unknown."""
        return self.queues.get(name, self.fallback)

    def names(self) -> tuple[str, ...]:
        """Stable list of configured queue names."""
        return tuple(self.queues.keys())
