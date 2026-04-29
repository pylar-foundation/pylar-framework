"""Behavioural tests for the notifications layer."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pytest

from pylar.mail import Mailable, Mailer, MemoryTransport, Message
from pylar.notifications import (
    ChannelDispatchError,
    LogChannel,
    MailChannel,
    Notifiable,
    Notification,
    NotificationDispatcher,
    UnknownChannelError,
)

# --------------------------------------------------------------------- fixtures


@dataclass(frozen=True)
class _User:
    email: str
    log_handle: str

    def routes_for(self, channel: str) -> str | None:
        if channel == "mail":
            return self.email
        if channel == "log":
            return self.log_handle
        return None


# --------------------------------------------------------------- mail channel


class _WelcomeMailable(Mailable):
    def __init__(self, recipient: str) -> None:
        self.recipient = recipient

    async def build(self) -> Message:
        return Message(
            to=(self.recipient,),
            subject="Welcome",
            text="Hello and welcome",
        )


class WelcomeNotification(Notification):
    def via(self) -> tuple[str, ...]:
        return ("mail",)

    def to_mail(self, notifiable: Notifiable) -> Mailable:
        recipient = notifiable.routes_for("mail")
        assert recipient is not None  # test invariant
        return _WelcomeMailable(recipient)


class BrokenMailNotification(Notification):
    def via(self) -> tuple[str, ...]:
        return ("mail",)

    def to_mail(self, notifiable: Notifiable) -> str:  # type: ignore[override]
        return "not a mailable"


class NoMailHookNotification(Notification):
    def via(self) -> tuple[str, ...]:
        return ("mail",)


# ---------------------------------------------------------------- log channel


class PingNotification(Notification):
    def via(self) -> tuple[str, ...]:
        return ("log",)

    def to_log(self, notifiable: Notifiable) -> str:
        return f"ping for {notifiable.routes_for('log')}"


# ----------------------------------------------------------------- multi-chan


class FanoutNotification(Notification):
    def via(self) -> tuple[str, ...]:
        return ("mail", "log")

    def to_mail(self, notifiable: Notifiable) -> Mailable:
        recipient = notifiable.routes_for("mail")
        assert recipient is not None
        return _WelcomeMailable(recipient)

    def to_log(self, notifiable: Notifiable) -> str:
        return "fanout"


# ------------------------------------------------------------------------ tests


@pytest.fixture
def transport() -> MemoryTransport:
    return MemoryTransport()


@pytest.fixture
def mailer(transport: MemoryTransport) -> Mailer:
    return Mailer(transport, default_from="noreply@example.com")


@pytest.fixture
def dispatcher(mailer: Mailer) -> NotificationDispatcher:
    d = NotificationDispatcher()
    d.register_channel(MailChannel(mailer))
    d.register_channel(LogChannel())
    return d


@pytest.fixture
def alice() -> _User:
    return _User(email="alice@example.com", log_handle="alice-handle")


async def test_mail_channel_delivers_via_mailer(
    dispatcher: NotificationDispatcher,
    transport: MemoryTransport,
    alice: _User,
) -> None:
    await dispatcher.send(alice, WelcomeNotification())
    assert len(transport.sent) == 1
    assert transport.sent[0].to == ("alice@example.com",)
    assert transport.sent[0].subject == "Welcome"


async def test_log_channel_writes_to_logger(
    dispatcher: NotificationDispatcher,
    alice: _User,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger="pylar.notifications"):
        await dispatcher.send(alice, PingNotification())
    assert any("ping for alice-handle" in r.message for r in caplog.records)


async def test_unknown_channel_raises(
    dispatcher: NotificationDispatcher, alice: _User
) -> None:
    class WeirdNotification(Notification):
        def via(self) -> tuple[str, ...]:
            return ("smoke-signal",)

    with pytest.raises(UnknownChannelError, match="smoke-signal"):
        await dispatcher.send(alice, WeirdNotification())


async def test_mail_channel_requires_to_mail(
    dispatcher: NotificationDispatcher, alice: _User
) -> None:
    with pytest.raises(ChannelDispatchError, match="to_mail"):
        await dispatcher.send(alice, NoMailHookNotification())


async def test_mail_channel_requires_mailable_return_type(
    dispatcher: NotificationDispatcher, alice: _User
) -> None:
    with pytest.raises(ChannelDispatchError, match="must return a Mailable"):
        await dispatcher.send(alice, BrokenMailNotification())


async def test_fanout_visits_every_channel_in_order(
    dispatcher: NotificationDispatcher,
    transport: MemoryTransport,
    alice: _User,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger="pylar.notifications"):
        await dispatcher.send(alice, FanoutNotification())
    assert len(transport.sent) == 1
    assert any("fanout" in r.message for r in caplog.records)


def test_dispatcher_introspection(dispatcher: NotificationDispatcher) -> None:
    assert dispatcher.has_channel("mail")
    assert dispatcher.has_channel("log")
    assert "mail" in dispatcher.channel_names()
    assert "log" in dispatcher.channel_names()
