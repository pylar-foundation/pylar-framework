"""Tests for event polish: MRO walk, dispatch_parallel, Subscriber."""

from __future__ import annotations

from pylar.events import Event, EventBus, Listener, Subscriber
from pylar.foundation.container import Container

_log: list[str] = []


class BaseOrderEvent(Event):
    pass


class OrderShipped(BaseOrderEvent):
    pass


class OrderRefunded(BaseOrderEvent):
    pass


class BaseListener(Listener[BaseOrderEvent]):
    async def handle(self, event: BaseOrderEvent) -> None:
        _log.append(f"base:{type(event).__name__}")


class ShippedListener(Listener[OrderShipped]):
    async def handle(self, event: OrderShipped) -> None:
        _log.append("shipped")


class FailingListener(Listener[OrderShipped]):
    async def handle(self, event: OrderShipped) -> None:
        raise RuntimeError("boom")


class SecondShippedListener(Listener[OrderShipped]):
    async def handle(self, event: OrderShipped) -> None:
        _log.append("second")


# ---------------------------------------------------------------- MRO walk


async def test_listener_on_parent_fires_for_subclass() -> None:
    _log.clear()
    bus = EventBus(Container())
    bus.listen(BaseOrderEvent, BaseListener)
    bus.listen(OrderShipped, ShippedListener)
    await bus.dispatch(OrderShipped())
    assert _log == ["shipped", "base:OrderShipped"]


async def test_listener_only_on_parent_fires_for_unrelated_subclass() -> None:
    _log.clear()
    bus = EventBus(Container())
    bus.listen(BaseOrderEvent, BaseListener)
    await bus.dispatch(OrderRefunded())
    assert _log == ["base:OrderRefunded"]


# ------------------------------------------------------- dispatch_parallel


async def test_dispatch_parallel_runs_concurrently() -> None:
    _log.clear()
    bus = EventBus(Container())
    bus.listen(OrderShipped, ShippedListener)
    bus.listen(OrderShipped, SecondShippedListener)
    await bus.dispatch_parallel(OrderShipped())
    assert sorted(_log) == ["second", "shipped"]


async def test_dispatch_parallel_aggregates_failures() -> None:
    _log.clear()
    bus = EventBus(Container())
    bus.listen(OrderShipped, ShippedListener)
    bus.listen(OrderShipped, FailingListener)
    try:
        await bus.dispatch_parallel(OrderShipped())
    except BaseExceptionGroup as group:
        assert len(group.exceptions) == 1
        assert isinstance(group.exceptions[0], RuntimeError)
    else:
        raise AssertionError("expected ExceptionGroup")


# ----------------------------------------------------------- Subscriber


class OrderSubscriber(Subscriber):
    def subscribe(self, bus: EventBus) -> None:
        bus.listen(OrderShipped, ShippedListener)
        bus.listen(OrderRefunded, BaseListener)


async def test_subscriber_attaches_multiple_listeners() -> None:
    _log.clear()
    bus = EventBus(Container())
    OrderSubscriber().subscribe(bus)
    await bus.dispatch(OrderShipped())
    await bus.dispatch(OrderRefunded())
    assert "shipped" in _log
    assert "base:OrderRefunded" in _log
