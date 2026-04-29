"""The :class:`NotificationDispatcher` — registers channels and fans notifications out to them."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pylar.notifications.contracts import Notifiable, NotificationChannel
from pylar.notifications.exceptions import (
    NotificationError,
    UnknownChannelError,
)
from pylar.notifications.notification import Notification

if TYPE_CHECKING:
    from pylar.foundation.container import Container


class NotificationDispatcher:
    """Routes a notification through every channel its ``via()`` lists.

    The dispatcher is application-scoped: channels are registered eagerly
    in :meth:`register_channel` (typically from the service provider's
    ``register`` phase) and looked up by string key when a notification
    arrives. The string key is *the* point at which notifications and
    channels meet — channel implementations themselves never compare
    names with each other.
    """

    def __init__(
        self,
        *,
        container: Container | None = None,
    ) -> None:
        self._channels: dict[str, NotificationChannel] = {}
        self._container = container

    def register_channel(self, channel: NotificationChannel) -> None:
        """Attach *channel* under its declared ``name``."""
        self._channels[channel.name] = channel

    def has_channel(self, name: str) -> bool:
        return name in self._channels

    def channel_names(self) -> tuple[str, ...]:
        return tuple(self._channels.keys())

    async def send(
        self,
        notifiable: Notifiable,
        notification: Notification,
    ) -> None:
        """Deliver *notification* to *notifiable* across every requested channel.

        Channels are visited in the order ``notification.via()`` returns
        them. The first channel to raise aborts the rest of the chain so
        the failure is visible — silent partial deliveries are a
        debugging nightmare and almost never the right default.

        Notifications with ``should_queue = True`` are not delivered
        inline. The dispatcher serialises them through
        :meth:`Notification.to_payload`, dispatches a generic
        :class:`pylar.notifications.jobs.DeliverNotificationJob`, and
        returns. A worker process re-runs the channel chain by calling
        :meth:`_send_inline`.
        """
        if getattr(type(notification), "should_queue", False):
            await self._dispatch_queued(notifiable, notification)
            return
        await self._send_inline(notifiable, notification)

    async def _send_inline(
        self,
        notifiable: Notifiable,
        notification: Notification,
    ) -> None:
        for channel_name in notification.via():
            if channel_name not in self._channels:
                raise UnknownChannelError(channel_name)
            await self._channels[channel_name].send(notifiable, notification)

    async def _dispatch_queued(
        self,
        notifiable: Notifiable,
        notification: Notification,
    ) -> None:
        from pylar.notifications.jobs import (
            DeliverNotificationJob,
            DeliverNotificationPayload,
        )
        from pylar.queue.dispatcher import Dispatcher

        if self._container is None or not self._container.has(Dispatcher):
            raise NotificationError(
                f"{type(notification).__qualname__} is queued but no "
                "Dispatcher is bound — register the queue service "
                "provider before sending queued notifications."
            )
        notification_cls = type(notification)
        payload_type = notification_cls.payload_type
        if payload_type is None:
            raise NotificationError(
                f"{notification_cls.__qualname__} is queued but does not "
                "declare a payload_type."
            )
        inner = notification.to_payload(notifiable)
        if not isinstance(inner, payload_type):
            raise NotificationError(
                f"{notification_cls.__qualname__}.to_payload() must return "
                f"a {payload_type.__qualname__} instance, "
                f"got {type(inner).__qualname__}"
            )
        dispatch_payload = DeliverNotificationPayload(
            notification_class=f"{notification_cls.__module__}."
            f"{notification_cls.__qualname__}",
            payload_type=f"{payload_type.__module__}.{payload_type.__qualname__}",
            payload_json=inner.model_dump_json(),
        )
        dispatcher = self._container.make(Dispatcher)
        await dispatcher.dispatch(DeliverNotificationJob, dispatch_payload)

    @staticmethod
    def fake() -> Any:
        """Return a recording :class:`FakeNotificationDispatcher` for tests.

        Drop-in for :class:`NotificationDispatcher` — controllers and
        services that depend on
        ``dispatcher: NotificationDispatcher`` accept the fake without
        changes when bound via
        ``container.instance(NotificationDispatcher,
        NotificationDispatcher.fake())``.
        """
        from pylar.testing.fakes import FakeNotificationDispatcher

        return FakeNotificationDispatcher()
