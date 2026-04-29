"""Recording test doubles for the framework's dispatcher-style services.

Each fake is a drop-in for the real component — controllers under
test that depend on the real class accept the fake without changes
when the test binds it via ``container.instance(Real, Fake())``.

The fakes mirror :class:`pylar.queue.FakeDispatcher` shipped with the
queue layer: every call is recorded in memory, then the test asserts
intent through ``assert_*`` helpers.
"""

from __future__ import annotations

from typing import Any

from pylar.events.event import Event
from pylar.mail.mailable import Mailable
from pylar.mail.message import Message
from pylar.notifications.contracts import Notifiable
from pylar.notifications.notification import Notification


class FakeMailer:
    """Drop-in replacement for :class:`pylar.mail.Mailer` that records sends."""

    def __init__(self) -> None:
        self._sent: list[Mailable] = []

    async def send(self, mailable: Mailable) -> Message:
        self._sent.append(mailable)
        # The recorded mailable is what the test inspects; we still
        # build the message so the contract matches the real Mailer.
        return await mailable.build()

    # ----------------------------------------------------------- inspection

    def sent(self, mailable_cls: type[Mailable] | None = None) -> list[Mailable]:
        if mailable_cls is None:
            return list(self._sent)
        return [m for m in self._sent if isinstance(m, mailable_cls)]

    def assert_sent(
        self,
        mailable_cls: type[Mailable],
        times: int | None = None,
    ) -> None:
        matches = self.sent(mailable_cls)
        if times is None:
            if not matches:
                raise AssertionError(
                    f"Expected {mailable_cls.__qualname__} to have been sent, "
                    f"but no matching mailable was recorded"
                )
            return
        if len(matches) != times:
            raise AssertionError(
                f"Expected {mailable_cls.__qualname__} to have been sent "
                f"{times} time(s), got {len(matches)}"
            )

    def assert_not_sent(self, mailable_cls: type[Mailable]) -> None:
        if self.sent(mailable_cls):
            raise AssertionError(
                f"Expected {mailable_cls.__qualname__} not to have been sent, "
                f"got {len(self.sent(mailable_cls))} call(s)"
            )

    def assert_nothing_sent(self) -> None:
        if self._sent:
            raise AssertionError(
                f"Expected no mail to have been sent, got {len(self._sent)} call(s)"
            )

    def clear(self) -> None:
        self._sent.clear()


class FakeEventBus:
    """Drop-in replacement for :class:`pylar.events.EventBus`."""

    def __init__(self) -> None:
        self._dispatched: list[Event] = []

    def listen(self, event_type: type[Event], listener_cls: Any) -> None:
        # Recorded for completeness but never invoked — the fake does
        # not actually run listeners.
        return None

    def listeners_for(self, event_type: type[Event]) -> tuple[Any, ...]:
        return ()

    async def dispatch(self, event: Event) -> None:
        self._dispatched.append(event)

    # ----------------------------------------------------------- inspection

    def dispatched(self, event_type: type[Event] | None = None) -> list[Event]:
        if event_type is None:
            return list(self._dispatched)
        return [e for e in self._dispatched if isinstance(e, event_type)]

    def assert_dispatched(
        self,
        event_type: type[Event],
        times: int | None = None,
    ) -> None:
        matches = self.dispatched(event_type)
        if times is None:
            if not matches:
                raise AssertionError(
                    f"Expected {event_type.__qualname__} to have been dispatched, "
                    f"but no matching event was recorded"
                )
            return
        if len(matches) != times:
            raise AssertionError(
                f"Expected {event_type.__qualname__} to have been dispatched "
                f"{times} time(s), got {len(matches)}"
            )

    def assert_not_dispatched(self, event_type: type[Event]) -> None:
        if self.dispatched(event_type):
            raise AssertionError(
                f"Expected {event_type.__qualname__} not to have been dispatched, "
                f"got {len(self.dispatched(event_type))} call(s)"
            )

    def assert_nothing_dispatched(self) -> None:
        if self._dispatched:
            raise AssertionError(
                f"Expected no events to have been dispatched, "
                f"got {len(self._dispatched)} call(s)"
            )

    def clear(self) -> None:
        self._dispatched.clear()


class FakeNotificationDispatcher:
    """Drop-in replacement for :class:`pylar.notifications.NotificationDispatcher`."""

    def __init__(self) -> None:
        self._sent: list[tuple[Notifiable, Notification]] = []

    def register_channel(self, channel: Any) -> None:
        return None

    def has_channel(self, name: str) -> bool:
        return True  # the fake accepts every channel

    def channel_names(self) -> tuple[str, ...]:
        return ()

    async def send(
        self,
        notifiable: Notifiable,
        notification: Notification,
    ) -> None:
        self._sent.append((notifiable, notification))

    # ----------------------------------------------------------- inspection

    def sent(
        self, notification_cls: type[Notification] | None = None
    ) -> list[tuple[Notifiable, Notification]]:
        if notification_cls is None:
            return list(self._sent)
        return [
            pair for pair in self._sent if isinstance(pair[1], notification_cls)
        ]

    def assert_sent(
        self,
        notification_cls: type[Notification],
        times: int | None = None,
    ) -> None:
        matches = self.sent(notification_cls)
        if times is None:
            if not matches:
                raise AssertionError(
                    f"Expected {notification_cls.__qualname__} to have been sent, "
                    f"but no matching notification was recorded"
                )
            return
        if len(matches) != times:
            raise AssertionError(
                f"Expected {notification_cls.__qualname__} to have been sent "
                f"{times} time(s), got {len(matches)}"
            )

    def assert_not_sent(self, notification_cls: type[Notification]) -> None:
        if self.sent(notification_cls):
            raise AssertionError(
                f"Expected {notification_cls.__qualname__} not to have been sent, "
                f"got {len(self.sent(notification_cls))} call(s)"
            )

    def assert_nothing_sent(self) -> None:
        if self._sent:
            raise AssertionError(
                f"Expected no notifications to have been sent, "
                f"got {len(self._sent)} call(s)"
            )

    def clear(self) -> None:
        self._sent.clear()
