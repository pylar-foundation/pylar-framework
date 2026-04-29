# mail/ — backlog

The mail polish batch landed:

* :class:`Attachment` — pydantic-frozen wire format with filename,
  content bytes, MIME type, and inline/CID fields. ``SmtpTransport``
  attaches them via ``EmailMessage.add_attachment``; cloud drivers
  will translate the same fields when they arrive.
* :class:`ViewMailable` — Mailable base that pulls a :class:`View`
  out of the container and renders Jinja templates for ``html_template``
  / ``text_template``. When only the HTML template is set the plain-text
  body is derived via a coarse tag strip so text-only clients still get
  readable content.
* :class:`MarkdownMailable` — renders the Markdown source to HTML via
  the ``markdown`` package (``pylar[mail-markdown]`` extra) and uses
  the source itself as the plain-text body.
* :meth:`Mailer.queue` + :class:`SendMailableJob` — dispatches a
  generic job carrying the qualified mailable class and a serialised
  :class:`JobPayload`. The worker resolves the class, revives the
  payload, calls :meth:`Mailable.from_payload`, and asks the bound
  :class:`Mailer` to send. Mailables opt in by setting
  ``payload_type`` and implementing ``to_payload`` / ``from_payload``.

What is still on the wishlist:

## Async-native SMTP

`SmtpTransport` wraps stdlib `smtplib` in `asyncio.to_thread` to keep the
core dependency footprint small. For high-volume senders this leaves
performance on the table. Add an opt-in `AiosmtpTransport` behind a
`pylar[mail-aiosmtp]` extra once a real workload demands it.

## Cloud / API transports

`SesTransport`, `MailgunTransport`, `PostmarkTransport`, `SendgridTransport`.
Each lives behind its own `pylar[mail-*]` extra. The Transport Protocol is
already small enough that adding them is mostly mechanical. The new
attachment fields translate one-for-one to each provider's multipart
upload format.

## Streaming attachment sources

`Attachment.content` is currently in-memory bytes. A future iteration
could accept an async iterator or a path so very large files don't have
to round-trip through RAM before reaching the SMTP server.
