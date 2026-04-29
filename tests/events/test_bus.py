"""Behavioural tests for :class:`EventBus`."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from pylar.events import (
    Event,
    EventBus,
    EventServiceProvider,
    Listener,
    ListenerRegistrationError,
)
from pylar.foundation import (
    AppConfig,
    Application,
    Container,
)

# --------------------------------------------------------------------- domain


@dataclass(frozen=True)
class UserRegistered(Event):
    user_id: int
    email: str


@dataclass(frozen=True)
class OrderShipped(Event):
    order_id: int


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []


class SendWelcomeEmail(Listener[UserRegistered]):
    def __init__(self, recorder: _Recorder) -> None:
        self.recorder = recorder

    async def handle(self, event: UserRegistered) -> None:
        self.recorder.calls.append(("welcome", event.email))


class CreateProfile(Listener[UserRegistered]):
    def __init__(self, recorder: _Recorder) -> None:
        self.recorder = recorder

    async def handle(self, event: UserRegistered) -> None:
        self.recorder.calls.append(("profile", event.user_id))


class FailingListener(Listener[UserRegistered]):
    def __init__(self, recorder: _Recorder) -> None:
        self.recorder = recorder

    async def handle(self, event: UserRegistered) -> None:
        self.recorder.calls.append(("fail", event.user_id))
        raise RuntimeError("listener failure")


class NotifyCustomer(Listener[OrderShipped]):
    def __init__(self, recorder: _Recorder) -> None:
        self.recorder = recorder

    async def handle(self, event: OrderShipped) -> None:
        self.recorder.calls.append(("notify", event.order_id))


@pytest.fixture
def container() -> Container:
    container = Container()
    container.instance(_Recorder, _Recorder())
    return container


@pytest.fixture
def bus(container: Container) -> EventBus:
    return EventBus(container)


# ------------------------------------------------------------------------ tests


async def test_dispatch_runs_listeners_in_registration_order(
    bus: EventBus, container: Container
) -> None:
    bus.listen(UserRegistered, SendWelcomeEmail)
    bus.listen(UserRegistered, CreateProfile)

    await bus.dispatch(UserRegistered(user_id=1, email="alice@example.com"))

    recorder = container.make(_Recorder)
    assert recorder.calls == [
        ("welcome", "alice@example.com"),
        ("profile", 1),
    ]


async def test_dispatch_isolates_listeners_per_event_type(
    bus: EventBus, container: Container
) -> None:
    bus.listen(UserRegistered, SendWelcomeEmail)
    bus.listen(OrderShipped, NotifyCustomer)

    await bus.dispatch(OrderShipped(order_id=42))

    recorder = container.make(_Recorder)
    assert recorder.calls == [("notify", 42)]


async def test_dispatch_with_no_listeners_is_a_noop(
    bus: EventBus, container: Container
) -> None:
    await bus.dispatch(UserRegistered(user_id=1, email="x@y.test"))
    assert container.make(_Recorder).calls == []


async def test_failing_listener_aborts_chain(
    bus: EventBus, container: Container
) -> None:
    bus.listen(UserRegistered, FailingListener)
    bus.listen(UserRegistered, CreateProfile)  # never runs

    with pytest.raises(RuntimeError, match="listener failure"):
        await bus.dispatch(UserRegistered(user_id=1, email="x@y.test"))

    recorder = container.make(_Recorder)
    assert recorder.calls == [("fail", 1)]


async def test_listener_dependencies_are_resolved_per_dispatch(
    bus: EventBus, container: Container
) -> None:
    bus.listen(UserRegistered, SendWelcomeEmail)

    await bus.dispatch(UserRegistered(user_id=1, email="a@a"))
    await bus.dispatch(UserRegistered(user_id=2, email="b@b"))

    recorder = container.make(_Recorder)
    assert recorder.calls == [("welcome", "a@a"), ("welcome", "b@b")]


def test_listen_rejects_non_event_class(bus: EventBus) -> None:
    class NotAnEvent:
        pass

    with pytest.raises(
        ListenerRegistrationError,
        match=r"subclass of pylar\.events\.Event",
    ):
        bus.listen(NotAnEvent, SendWelcomeEmail)  # type: ignore[arg-type]


def test_listen_rejects_non_listener_class(bus: EventBus) -> None:
    class NotAListener:
        pass

    with pytest.raises(
        ListenerRegistrationError,
        match=r"subclass of pylar\.events\.Listener",
    ):
        bus.listen(UserRegistered, NotAListener)  # type: ignore[arg-type]


def test_listeners_for_returns_registered_classes(bus: EventBus) -> None:
    bus.listen(UserRegistered, SendWelcomeEmail)
    bus.listen(UserRegistered, CreateProfile)
    assert bus.listeners_for(UserRegistered) == (SendWelcomeEmail, CreateProfile)
    assert bus.listeners_for(OrderShipped) == ()


# ----------------------------------------------------------------- provider


_PROVIDER_RECORDER = _Recorder()


class _AppEventProvider(EventServiceProvider):
    def register_events(self, bus: EventBus) -> None:
        bus.listen(UserRegistered, SendWelcomeEmail)


async def test_event_service_provider_binds_singleton_bus() -> None:
    from pathlib import Path

    app = Application(
        base_path=Path("/tmp/pylar-events-test"),
        config=AppConfig(name="events-test", debug=True, providers=(_AppEventProvider,)),
    )
    app.container.instance(_Recorder, _PROVIDER_RECORDER)
    _PROVIDER_RECORDER.calls.clear()

    await app.bootstrap()

    bus_a = app.container.make(EventBus)
    bus_b = app.container.make(EventBus)
    assert bus_a is bus_b
    assert bus_a.listeners_for(UserRegistered) == (SendWelcomeEmail,)

    await bus_a.dispatch(UserRegistered(user_id=99, email="from-provider@x"))
    assert _PROVIDER_RECORDER.calls == [("welcome", "from-provider@x")]

    await app.shutdown()
