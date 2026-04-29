"""Protocols for notifiable targets and notification channels."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pylar.notifications.notification import Notification


@runtime_checkable
class Notifiable(Protocol):
    """Anything that can receive notifications.

    A notifiable supplies an address per channel: an email for the mail
    channel, a webhook URL for the broadcast channel, a phone number for
    SMS, and so on. Implementations return ``None`` to opt out of a
    channel — the dispatcher then skips it for that recipient.
    """

    def routes_for(self, channel: str) -> str | None: ...


@runtime_checkable
class NotificationChannel(Protocol):
    """A delivery mechanism — mail, SMS, broadcast, slack, …

    Channels are registered under a string key inside the
    :class:`NotificationDispatcher`. The key is what notifications return
    from their ``via()`` hook; channels themselves don't compare names.
    """

    name: str

    async def send(self, notifiable: Notifiable, notification: Notification) -> None: ...
