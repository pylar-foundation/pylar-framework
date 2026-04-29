"""Generic queue job that re-runs a queued :class:`Notification`."""

from __future__ import annotations

import importlib
from typing import Any, ClassVar

from pylar.foundation.container import Container
from pylar.notifications.dispatcher import NotificationDispatcher
from pylar.notifications.exceptions import NotificationError
from pylar.notifications.notification import Notification
from pylar.queue.job import Job
from pylar.queue.payload import JobPayload


class DeliverNotificationPayload(JobPayload):
    """Wire format for a queued notification dispatch."""

    notification_class: str
    payload_type: str
    payload_json: str


class DeliverNotificationJob(Job[DeliverNotificationPayload]):
    """Generic worker entry point for queued notifications."""

    payload_type: ClassVar[type[JobPayload]] = DeliverNotificationPayload

    def __init__(
        self,
        container: Container,
        dispatcher: NotificationDispatcher,
    ) -> None:
        self._container = container
        self._dispatcher = dispatcher

    async def handle(self, payload: DeliverNotificationPayload) -> None:
        notification_cls = self._resolve(payload.notification_class, Notification)  # type: ignore[type-abstract]
        inner_payload_cls = self._resolve(payload.payload_type, JobPayload)
        inner = inner_payload_cls.model_validate_json(payload.payload_json)
        notifiable, notification = notification_cls.from_payload(
            self._container, inner
        )
        # Re-run the channel chain inline now that we are on the worker
        # — but with should_queue forcibly disabled so we don't recurse.
        await self._dispatcher._send_inline(notifiable, notification)

    @staticmethod
    def _resolve[T](qualified_name: str, base: type[T]) -> type[T]:
        module_name, _, class_name = qualified_name.rpartition(".")
        if not module_name or not class_name:
            raise NotificationError(
                f"{qualified_name!r} is not a fully qualified name"
            )
        module = importlib.import_module(module_name)
        obj: Any = getattr(module, class_name, None)
        if not isinstance(obj, type) or not issubclass(obj, base):
            raise NotificationError(
                f"{qualified_name} resolved to {obj!r}, "
                f"not a {base.__qualname__} subclass"
            )
        return obj
