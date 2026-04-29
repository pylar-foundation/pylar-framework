"""Mail transport that writes to a logger instead of sending bytes anywhere."""

from __future__ import annotations

import logging

from pylar.mail.exceptions import TransportError
from pylar.mail.message import Message


class LogTransport:
    """Useful in development — emails appear in the application log.

    Pairs nicely with the standard ``logging`` configuration: point a
    handler at a file (or stdout) and you get a searchable record of
    every outbound message without configuring an SMTP relay locally.
    """

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger("pylar.mail")

    async def send(self, message: Message) -> None:
        if not message.has_body():
            raise TransportError(
                f"Refusing to send message to {message.to!r} with empty body"
            )
        body = message.text or message.html or ""
        self._logger.info(
            "MAIL to=%s subject=%s\n%s",
            ",".join(message.to),
            message.subject,
            body,
        )
