"""SMTP transport built on the stdlib's :mod:`smtplib`.

The driver intentionally relies on Python's batteries rather than
``aiosmtplib``: it dispatches the synchronous SMTP call through
:func:`asyncio.to_thread` so the event loop never blocks. This keeps
pylar's core dependency footprint small while still presenting an
async API to the caller. Installations that need true async-native
SMTP can swap in their own driver — the contract is one method.
"""

from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage

from pylar.mail.exceptions import TransportError
from pylar.mail.message import Attachment, Message


class SmtpTransport:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str = "",
        password: str = "",
        use_tls: bool = True,
        use_ssl: bool = False,
        timeout: float = 30.0,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._use_tls = use_tls
        self._use_ssl = use_ssl
        self._timeout = timeout

    async def send(self, message: Message) -> None:
        if not message.has_body():
            raise TransportError(
                f"Refusing to send message to {message.to!r} with empty body"
            )
        await asyncio.to_thread(self._send_sync, message)

    # ------------------------------------------------------------------ internals

    def _send_sync(self, message: Message) -> None:
        em = self._build_email(message)
        try:
            if self._use_ssl:
                with smtplib.SMTP_SSL(self._host, self._port, timeout=self._timeout) as server:
                    self._authenticate_and_send(server, em)
            else:
                with smtplib.SMTP(self._host, self._port, timeout=self._timeout) as server:
                    if self._use_tls:
                        server.starttls()
                    self._authenticate_and_send(server, em)
        except smtplib.SMTPException as exc:
            raise TransportError(f"SMTP delivery failed: {exc}") from exc

    def _authenticate_and_send(
        self, server: smtplib.SMTP, em: EmailMessage
    ) -> None:
        if self._username:
            server.login(self._username, self._password)
        server.send_message(em)

    @staticmethod
    def _build_email(message: Message) -> EmailMessage:
        em = EmailMessage()
        em["Subject"] = message.subject
        if message.from_address:
            em["From"] = message.from_address
        em["To"] = ", ".join(message.to)
        if message.cc:
            em["Cc"] = ", ".join(message.cc)
        if message.bcc:
            em["Bcc"] = ", ".join(message.bcc)
        if message.reply_to:
            em["Reply-To"] = message.reply_to

        if message.text and message.html:
            em.set_content(message.text)
            em.add_alternative(message.html, subtype="html")
        elif message.html:
            em.set_content(message.html, subtype="html")
        elif message.text:
            em.set_content(message.text)

        for attachment in message.attachments:
            SmtpTransport._attach(em, attachment)
        return em

    @staticmethod
    def _attach(em: EmailMessage, attachment: Attachment) -> None:
        maintype, _, subtype = attachment.content_type.partition("/")
        if not subtype:
            maintype, subtype = "application", "octet-stream"
        if attachment.inline:
            em.add_attachment(
                attachment.content,
                maintype=maintype,
                subtype=subtype,
                filename=attachment.filename,
                disposition="inline",
                cid=f"<{attachment.cid}>" if attachment.cid else None,
            )
        else:
            em.add_attachment(
                attachment.content,
                maintype=maintype,
                subtype=subtype,
                filename=attachment.filename,
            )
