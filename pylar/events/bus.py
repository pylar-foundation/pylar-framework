"""The :class:`EventBus` — registers listeners and dispatches events to them."""

from __future__ import annotations

import asyncio
from typing import Any, TypeVar

from pylar.events.event import Event
from pylar.events.exceptions import ListenerRegistrationError
from pylar.events.listener import Listener
from pylar.foundation.container import Container

EventT = TypeVar("EventT", bound=Event)


class EventBus:
    """A typed in-process event dispatcher.

    Registration maps an exact event type to a list of listener *classes* —
    not instances. The bus only constructs a listener via the container at
    the moment its event is dispatched, so per-listener dependencies are
    resolved fresh each time and the registry stays cheap.

    Dispatch order matches registration order. Listeners run sequentially;
    if any listener raises, dispatch aborts and the exception propagates to
    the caller. Parallel dispatch is intentionally **not** offered by the
    base implementation — it would hide failures and is rarely the right
    default for domain events.
    """

    def __init__(self, container: Container) -> None:
        self._container = container
        self._listeners: dict[type[Event], list[type[Listener[Any]]]] = {}

    # ------------------------------------------------------------------ register

    def listen(
        self,
        event_type: type[EventT],
        listener_cls: type[Listener[EventT]],
    ) -> None:
        """Attach *listener_cls* to every dispatch of *event_type*."""
        if not isinstance(event_type, type) or not issubclass(event_type, Event):
            raise ListenerRegistrationError(
                f"{event_type!r} must be a subclass of pylar.events.Event"
            )
        if not isinstance(listener_cls, type) or not issubclass(listener_cls, Listener):
            raise ListenerRegistrationError(
                f"{listener_cls!r} must be a subclass of pylar.events.Listener"
            )
        bucket = self._listeners.setdefault(event_type, [])
        bucket.append(listener_cls)

    def listeners_for(self, event_type: type[Event]) -> tuple[type[Listener[Any]], ...]:
        """Return the listener classes registered for *event_type*."""
        return tuple(self._listeners.get(event_type, ()))

    # ------------------------------------------------------------------ dispatch

    def _walk_listeners(
        self, event_type: type[Event]
    ) -> list[type[Listener[Any]]]:
        """Return every listener registered against this event class or its bases.

        Walks ``type(event).__mro__`` so a listener bound to a parent
        class also fires for subclass events. The order is:
        listeners on the most-derived class first, then each ancestor.
        Within a single class registration order is preserved.
        """
        collected: list[type[Listener[Any]]] = []
        for ancestor in event_type.__mro__:
            if ancestor is object:
                continue
            for listener_cls in self._listeners.get(ancestor, ()):
                if listener_cls not in collected:
                    collected.append(listener_cls)
        return collected

    async def dispatch(self, event: EventT) -> None:
        """Run every listener registered for ``type(event)`` (or any base) in order.

        Listeners run sequentially. The first listener that raises aborts
        the rest of the chain and the exception bubbles to the caller.
        Listeners with ``should_queue = True`` are not invoked inline:
        the bus dispatches a generic :class:`DispatchListenerJob`
        through the bound :class:`pylar.queue.Dispatcher` so the work
        runs on a worker process instead.

        Listener resolution walks the event class's MRO so a listener
        bound to a parent ``OrderEvent`` fires for every subclass. Use
        :meth:`listen` against a specific subclass when you want exact
        matching only.
        """
        for listener_cls in self._walk_listeners(type(event)):
            if getattr(listener_cls, "should_queue", False):
                await self._dispatch_queued(listener_cls, event)
                continue
            listener = self._container.make(listener_cls)
            await listener.handle(event)

    async def dispatch_parallel(self, event: EventT) -> None:
        """Run every listener for *event* concurrently via :func:`asyncio.gather`.

        Useful when listeners are independent (notification fan-out,
        analytics ping, cache warm-up) and the request handler does
        not want to wait for a sequential chain. Failures from
        individual listeners surface as a single :class:`ExceptionGroup`
        so the caller can inspect them collectively.
        """
        tasks = []
        for listener_cls in self._walk_listeners(type(event)):
            if getattr(listener_cls, "should_queue", False):
                tasks.append(self._dispatch_queued(listener_cls, event))
                continue
            listener = self._container.make(listener_cls)
            tasks.append(listener.handle(event))
        if not tasks:
            return
        results = await asyncio.gather(*tasks, return_exceptions=True)
        errors = [r for r in results if isinstance(r, BaseException)]
        if errors:
            raise BaseExceptionGroup("dispatch_parallel listener failures", errors)

    async def _dispatch_queued(
        self,
        listener_cls: type[Listener[Any]],
        event: Event,
    ) -> None:
        from pydantic import BaseModel

        from pylar.events.exceptions import ListenerRegistrationError
        from pylar.events.queued import (
            DispatchListenerJob,
            DispatchListenerPayload,
        )
        from pylar.queue.dispatcher import Dispatcher

        if not isinstance(event, BaseModel):
            raise ListenerRegistrationError(
                f"{type(event).__qualname__} must be a pydantic BaseModel "
                f"to be delivered to a queued listener "
                f"({listener_cls.__qualname__})."
            )
        if not self._container.has(Dispatcher):
            raise ListenerRegistrationError(
                f"{listener_cls.__qualname__} is queued but no Dispatcher "
                "is bound — register the queue service provider."
            )
        dispatcher = self._container.make(Dispatcher)
        payload = DispatchListenerPayload(
            listener_class=f"{listener_cls.__module__}.{listener_cls.__qualname__}",
            event_class=f"{type(event).__module__}.{type(event).__qualname__}",
            event_json=event.model_dump_json(),
        )
        await dispatcher.dispatch(DispatchListenerJob, payload)

    @staticmethod
    def fake() -> Any:
        """Return a recording :class:`FakeEventBus` for tests.

        Drop-in for :class:`EventBus` — controllers and services that
        depend on ``bus: EventBus`` accept the fake without changes
        when bound via ``container.instance(EventBus, EventBus.fake())``.
        """
        from pylar.testing.fakes import FakeEventBus

        return FakeEventBus()
