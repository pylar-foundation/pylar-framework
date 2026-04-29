"""Tests for queued notifications."""

from __future__ import annotations

from typing import ClassVar

from pylar.foundation.container import Container
from pylar.notifications import (
    DeliverNotificationJob,
    DeliverNotificationPayload,
    Notifiable,
    Notification,
    NotificationDispatcher,
)
from pylar.notifications.contracts import NotificationChannel
from pylar.queue import Dispatcher, JobPayload, MemoryQueue, Worker


class _User:
    """Tiny in-memory notifiable for the test."""

    _registry: ClassVar[dict[int, _User]] = {}

    def __init__(self, id: int, email: str) -> None:
        self.id = id
        self.email = email
        _User._registry[id] = self

    def routes_for(self, channel: str) -> str | None:
        if channel == "log":
            return self.email
        return None

    @classmethod
    def get(cls, id: int) -> _User:
        return cls._registry[id]


class _RecordingChannel(NotificationChannel):
    name = "log"

    def __init__(self) -> None:
        self.delivered: list[tuple[str, str]] = []

    async def send(
        self,
        notifiable: Notifiable,
        notification: Notification,
    ) -> None:
        addr = notifiable.routes_for("log")
        assert addr is not None
        # Notifications carry the rendering through a hook the channel knows.
        text = notification.to_log()  # type: ignore[attr-defined]
        self.delivered.append((addr, text))


class _GreetingPayload(JobPayload):
    user_id: int
    body: str


class GreetingNotification(Notification):
    """Queueable notification — opt-in via should_queue + payload pair."""

    should_queue: ClassVar[bool] = True
    payload_type: ClassVar[type[JobPayload] | None] = _GreetingPayload

    def __init__(self, body: str) -> None:
        self.body = body

    def via(self) -> tuple[str, ...]:
        return ("log",)

    def to_log(self) -> str:
        return self.body

    def to_payload(self, notifiable: Notifiable) -> JobPayload:
        assert isinstance(notifiable, _User)
        return _GreetingPayload(user_id=notifiable.id, body=self.body)

    @classmethod
    def from_payload(
        cls,
        container: Container,
        payload: JobPayload,
    ) -> tuple[Notifiable, GreetingNotification]:
        assert isinstance(payload, _GreetingPayload)
        return _User.get(payload.user_id), cls(payload.body)


async def test_inline_notification_runs_immediately() -> None:
    container = Container()
    dispatcher = NotificationDispatcher(container=container)
    channel = _RecordingChannel()
    dispatcher.register_channel(channel)

    class InlineGreeting(Notification):
        def __init__(self, body: str) -> None:
            self.body = body

        def via(self) -> tuple[str, ...]:
            return ("log",)

        def to_log(self) -> str:
            return self.body

    user = _User(1, "a@b.com")
    await dispatcher.send(user, InlineGreeting("hi"))
    assert channel.delivered == [("a@b.com", "hi")]


async def test_queued_notification_dispatches_through_queue() -> None:
    queue = MemoryQueue()
    container = Container()
    container.instance(Container, container)
    container.instance(Dispatcher, Dispatcher(queue))

    notification_dispatcher = NotificationDispatcher(container=container)
    channel = _RecordingChannel()
    notification_dispatcher.register_channel(channel)
    container.instance(NotificationDispatcher, notification_dispatcher)

    user = _User(2, "b@c.com")
    await notification_dispatcher.send(user, GreetingNotification("queued-hi"))
    assert channel.delivered == []  # not yet — sitting on the queue

    worker = Worker(queue, container)
    assert await worker.process_next(timeout=0.05) is True
    failed = await queue.failed_records()
    assert failed == [], failed[0].error if failed else ""
    assert channel.delivered == [("b@c.com", "queued-hi")]


async def test_deliver_job_round_trip_directly() -> None:
    container = Container()
    container.instance(Container, container)
    notification_dispatcher = NotificationDispatcher(container=container)
    channel = _RecordingChannel()
    notification_dispatcher.register_channel(channel)
    container.instance(NotificationDispatcher, notification_dispatcher)

    user = _User(3, "c@d.com")
    inner = GreetingNotification("direct").to_payload(user)
    job = DeliverNotificationJob(container, notification_dispatcher)
    await job.handle(
        DeliverNotificationPayload(
            notification_class=f"{GreetingNotification.__module__}."
            f"{GreetingNotification.__qualname__}",
            payload_type=f"{_GreetingPayload.__module__}.{_GreetingPayload.__qualname__}",
            payload_json=inner.model_dump_json(),
        )
    )
    assert channel.delivered == [("c@d.com", "direct")]
