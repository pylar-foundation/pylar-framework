"""Multi-channel notifications layer."""

from pylar.notifications.channels.database import DatabaseChannel
from pylar.notifications.channels.log import LogChannel
from pylar.notifications.channels.mail import MailChannel
from pylar.notifications.contracts import Notifiable, NotificationChannel
from pylar.notifications.dispatcher import NotificationDispatcher
from pylar.notifications.exceptions import (
    ChannelDispatchError,
    NotificationError,
    UnknownChannelError,
)
from pylar.notifications.jobs import (
    DeliverNotificationJob,
    DeliverNotificationPayload,
)
from pylar.notifications.notification import Notification
from pylar.notifications.provider import NotificationServiceProvider

__all__ = [
    "ChannelDispatchError",
    "DatabaseChannel",
    "DeliverNotificationJob",
    "DeliverNotificationPayload",
    "LogChannel",
    "MailChannel",
    "Notifiable",
    "Notification",
    "NotificationChannel",
    "NotificationDispatcher",
    "NotificationError",
    "NotificationServiceProvider",
    "UnknownChannelError",
]
