"""Concrete notification channels bundled with pylar."""

from pylar.notifications.channels.log import LogChannel
from pylar.notifications.channels.mail import MailChannel

__all__ = ["LogChannel", "MailChannel"]
