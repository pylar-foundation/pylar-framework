"""Tests for the recording mail, event bus, and notification fakes."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from pylar.events import Event, EventBus
from pylar.mail import Mailable, Mailer, Message
from pylar.notifications import (
    Notification,
    NotificationDispatcher,
)

# --------------------------------------------------------- mail fixtures


class WelcomeMailable(Mailable):
    def __init__(self, recipient: str) -> None:
        self.recipient = recipient

    async def build(self) -> Message:
        return Message(to=(self.recipient,), subject="hi", text="hello")


class GoodbyeMailable(Mailable):
    def __init__(self, recipient: str) -> None:
        self.recipient = recipient

    async def build(self) -> Message:
        return Message(to=(self.recipient,), subject="bye", text="bye")


# ---------------------------------------------------------- event fixtures


@dataclass(frozen=True)
class UserRegistered(Event):
    user_id: int


@dataclass(frozen=True)
class OrderShipped(Event):
    order_id: int


# ----------------------------------------------------- notification fixtures


class WelcomeNotification(Notification):
    def via(self) -> tuple[str, ...]:
        return ("mail",)


class _NoopNotifiable:
    def routes_for(self, channel: str) -> str | None:
        return None


# ------------------------------------------------------------------- mail


async def test_fake_mailer_records_sends() -> None:
    fake = Mailer.fake()
    await fake.send(WelcomeMailable("alice@example.com"))
    await fake.send(WelcomeMailable("bob@example.com"))
    await fake.send(GoodbyeMailable("alice@example.com"))

    fake.assert_sent(WelcomeMailable, times=2)
    fake.assert_sent(GoodbyeMailable)


async def test_fake_mailer_assert_failures() -> None:
    fake = Mailer.fake()
    with pytest.raises(AssertionError, match="to have been sent"):
        fake.assert_sent(WelcomeMailable)

    await fake.send(WelcomeMailable("x"))
    with pytest.raises(AssertionError, match="not to have been sent"):
        fake.assert_not_sent(WelcomeMailable)


async def test_fake_mailer_nothing_sent() -> None:
    fake = Mailer.fake()
    fake.assert_nothing_sent()
    await fake.send(WelcomeMailable("x"))
    with pytest.raises(AssertionError):
        fake.assert_nothing_sent()


async def test_fake_mailer_sent_filter() -> None:
    fake = Mailer.fake()
    await fake.send(WelcomeMailable("a"))
    await fake.send(WelcomeMailable("b"))
    await fake.send(GoodbyeMailable("c"))
    welcomes = fake.sent(WelcomeMailable)
    assert len(welcomes) == 2
    assert all(isinstance(m, WelcomeMailable) for m in welcomes)


async def test_fake_mailer_clear() -> None:
    fake = Mailer.fake()
    await fake.send(WelcomeMailable("x"))
    fake.clear()
    fake.assert_nothing_sent()


# ------------------------------------------------------------- event bus


async def test_fake_event_bus_records_dispatches() -> None:
    fake = EventBus.fake()
    await fake.dispatch(UserRegistered(user_id=1))
    await fake.dispatch(UserRegistered(user_id=2))
    await fake.dispatch(OrderShipped(order_id=99))

    fake.assert_dispatched(UserRegistered, times=2)
    fake.assert_dispatched(OrderShipped)


async def test_fake_event_bus_filters_by_type() -> None:
    fake = EventBus.fake()
    await fake.dispatch(UserRegistered(user_id=1))
    await fake.dispatch(OrderShipped(order_id=99))
    users = fake.dispatched(UserRegistered)
    assert [e.user_id for e in users] == [1]  # type: ignore[attr-defined]


async def test_fake_event_bus_assert_failures() -> None:
    fake = EventBus.fake()
    with pytest.raises(AssertionError):
        fake.assert_dispatched(UserRegistered)

    await fake.dispatch(UserRegistered(user_id=1))
    with pytest.raises(AssertionError):
        fake.assert_not_dispatched(UserRegistered)


async def test_fake_event_bus_nothing_dispatched() -> None:
    fake = EventBus.fake()
    fake.assert_nothing_dispatched()
    await fake.dispatch(UserRegistered(user_id=1))
    with pytest.raises(AssertionError):
        fake.assert_nothing_dispatched()


# ------------------------------------------------------- notification fake


async def test_fake_notification_dispatcher_records_sends() -> None:
    fake = NotificationDispatcher.fake()
    target = _NoopNotifiable()
    await fake.send(target, WelcomeNotification())
    await fake.send(target, WelcomeNotification())

    fake.assert_sent(WelcomeNotification, times=2)


async def test_fake_notification_dispatcher_assert_not_sent() -> None:
    fake = NotificationDispatcher.fake()
    fake.assert_not_sent(WelcomeNotification)

    await fake.send(_NoopNotifiable(), WelcomeNotification())
    with pytest.raises(AssertionError):
        fake.assert_not_sent(WelcomeNotification)


async def test_fake_notification_dispatcher_nothing_sent() -> None:
    fake = NotificationDispatcher.fake()
    fake.assert_nothing_sent()
    await fake.send(_NoopNotifiable(), WelcomeNotification())
    with pytest.raises(AssertionError):
        fake.assert_nothing_sent()


def test_fake_notification_dispatcher_register_channel_is_noop() -> None:
    fake = NotificationDispatcher.fake()
    fake.register_channel(object())  # accepts anything
    assert fake.has_channel("anything")  # always true
