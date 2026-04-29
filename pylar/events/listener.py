"""Base class for typed event listeners."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from pylar.events.event import Event


class Listener[EventT: Event](ABC):
    """A handler for a single event type.

    Listeners are constructed by the container, so their ``__init__`` can
    declare any dependencies the auto-wiring resolver knows how to satisfy.
    The ``handle`` method receives an instance of the concrete event class
    the listener was registered for; the type parameter is purely for the
    type checker — pylar dispatches by exact class match, not subclass.

    Set :attr:`should_queue` to ``True`` to push the listener invocation
    onto the queue layer instead of running it inline. The bus uses a
    generic :class:`pylar.events.queued.DispatchListenerJob` for the
    hand-off, so subclasses do not have to write their own job — they
    only need to be importable on the worker side and the event itself
    must be JSON-serialisable through pydantic.
    """

    #: Opt the listener into queue dispatch. The bus serialises the
    #: event, pushes a generic ``DispatchListenerJob``, and the worker
    #: re-runs the listener inside its own scope.
    should_queue: ClassVar[bool] = False

    @abstractmethod
    async def handle(self, event: EventT) -> None:
        """Process *event*. Raise to abort the dispatch chain."""
