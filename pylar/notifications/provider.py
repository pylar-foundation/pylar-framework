"""Service provider that wires the notifications layer."""

from __future__ import annotations

from pylar.foundation.container import Container
from pylar.foundation.provider import ServiceProvider
from pylar.mail.mailer import Mailer
from pylar.notifications.channels.log import LogChannel
from pylar.notifications.channels.mail import MailChannel
from pylar.notifications.dispatcher import NotificationDispatcher


class NotificationServiceProvider(ServiceProvider):
    """Bind a :class:`NotificationDispatcher` and register the bundled channels.

    The default registration includes ``mail`` (resolved through the
    :class:`Mailer` already in the container) and ``log``. User projects
    subclass this provider and override :meth:`register_channels` to
    register additional channels in one place — same pattern as
    :class:`EventServiceProvider`.
    """

    def register(self, container: Container) -> None:
        dispatcher = NotificationDispatcher(container=container)
        self.register_channels(dispatcher)
        container.singleton(NotificationDispatcher, lambda: dispatcher)

    def register_channels(self, dispatcher: NotificationDispatcher) -> None:
        """Register channels into *dispatcher*. Override to add more."""
        if self.app.container.has(Mailer):
            mailer = self.app.container.make(Mailer)
            dispatcher.register_channel(MailChannel(mailer))
        dispatcher.register_channel(LogChannel())
