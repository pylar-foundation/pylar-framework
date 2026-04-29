"""Tests for queued listeners."""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel

from pylar.events import EventBus, Listener
from pylar.events.event import Event
from pylar.events.queued import (
    DispatchListenerJob,
    DispatchListenerPayload,
)
from pylar.foundation.container import Container
from pylar.queue import Dispatcher, MemoryQueue, Worker

_seen: list[str] = []


class GreetingEvent(Event, BaseModel):
    name: str


class InlineListener(Listener[GreetingEvent]):
    async def handle(self, event: GreetingEvent) -> None:
        _seen.append(f"inline:{event.name}")


class QueuedGreetingListener(Listener[GreetingEvent]):
    should_queue: ClassVar[bool] = True

    async def handle(self, event: GreetingEvent) -> None:
        _seen.append(f"queued:{event.name}")


async def test_inline_listener_runs_immediately() -> None:
    _seen.clear()
    container = Container()
    bus = EventBus(container)
    bus.listen(GreetingEvent, InlineListener)
    await bus.dispatch(GreetingEvent(name="Ada"))
    assert _seen == ["inline:Ada"]


async def test_queued_listener_dispatches_through_queue() -> None:
    _seen.clear()
    queue = MemoryQueue()
    container = Container()
    container.instance(Container, container)
    container.instance(Dispatcher, Dispatcher(queue))

    bus = EventBus(container)
    bus.listen(GreetingEvent, QueuedGreetingListener)

    await bus.dispatch(GreetingEvent(name="Bea"))
    # Inline didn't run yet — work is sitting on the queue.
    assert _seen == []

    worker = Worker(queue, container)
    assert await worker.process_next(timeout=0.05) is True
    failed = await queue.failed_records()
    assert failed == [], failed[0].error if failed else ""
    assert _seen == ["queued:Bea"]


async def test_queued_listener_payload_round_trip() -> None:
    """Direct invocation of the generic dispatch job."""
    _seen.clear()
    container = Container()
    container.instance(Container, container)
    job = DispatchListenerJob(container)
    event = GreetingEvent(name="Carol")
    await job.handle(
        DispatchListenerPayload(
            listener_class=f"{QueuedGreetingListener.__module__}."
            f"{QueuedGreetingListener.__qualname__}",
            event_class=f"{GreetingEvent.__module__}.{GreetingEvent.__qualname__}",
            event_json=event.model_dump_json(),
        )
    )
    assert _seen == ["queued:Carol"]
