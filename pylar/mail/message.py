"""Wire-format for an outgoing email."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Attachment(BaseModel):
    """A single binary attachment carried by a :class:`Message`.

    ``filename`` is what recipients see in their mail client. ``content``
    is the raw bytes. ``content_type`` defaults to
    ``application/octet-stream`` — transports that care about MIME parts
    (notably :class:`pylar.mail.SmtpTransport`) split it into ``maintype``
    and ``subtype``.

    Inline attachments (e.g. ``<img src="cid:logo">`` references in HTML)
    are supported by setting ``inline=True`` together with an explicit
    ``cid``. The SMTP driver sets ``Content-Disposition: inline`` and
    adds a matching ``Content-ID`` header; cloud drivers translate the
    same fields to their respective multipart payloads.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    filename: str
    content: bytes
    content_type: str = "application/octet-stream"
    inline: bool = False
    cid: str | None = None


class Message(BaseModel):
    """A fully built email ready for a :class:`Transport` to deliver.

    Constructed by :class:`Mailable` subclasses inside their ``build``
    method. Either ``html`` or ``text`` (or both) must be present —
    transports refuse messages with no body.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    to: tuple[str, ...]
    subject: str
    html: str | None = None
    text: str | None = None
    from_address: str = Field(default="", alias="from")
    cc: tuple[str, ...] = ()
    bcc: tuple[str, ...] = ()
    reply_to: str | None = None
    attachments: tuple[Attachment, ...] = ()

    def has_body(self) -> bool:
        return bool(self.html or self.text)
