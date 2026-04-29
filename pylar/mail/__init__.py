"""Async typed mail layer with pluggable transports."""

from pylar.mail.config import MailConfig
from pylar.mail.drivers.log import LogTransport
from pylar.mail.drivers.memory import MemoryTransport
from pylar.mail.drivers.smtp import SmtpTransport
from pylar.mail.exceptions import (
    MailableDefinitionError,
    MailError,
    TransportError,
)
from pylar.mail.jobs import SendMailableJob, SendMailablePayload
from pylar.mail.mailable import Mailable, MarkdownMailable, ViewMailable
from pylar.mail.mailer import Mailer
from pylar.mail.message import Attachment, Message
from pylar.mail.provider import MailServiceProvider
from pylar.mail.transport import Transport

__all__ = [
    "Attachment",
    "LogTransport",
    "MailConfig",
    "MailError",
    "MailServiceProvider",
    "Mailable",
    "MailableDefinitionError",
    "Mailer",
    "MarkdownMailable",
    "MemoryTransport",
    "Message",
    "SendMailableJob",
    "SendMailablePayload",
    "SmtpTransport",
    "Transport",
    "TransportError",
    "ViewMailable",
]
