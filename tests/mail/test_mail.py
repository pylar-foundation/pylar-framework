"""Behavioural tests for the mail layer."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import ClassVar, Self

import pytest

from pylar.foundation.container import Container
from pylar.mail import (
    Attachment,
    LogTransport,
    Mailable,
    MailableDefinitionError,
    Mailer,
    MarkdownMailable,
    MemoryTransport,
    Message,
    SendMailableJob,
    SendMailablePayload,
    Transport,
    TransportError,
    ViewMailable,
)
from pylar.queue import Dispatcher, JobPayload, MemoryQueue
from pylar.views import JinjaRenderer, View

# --------------------------------------------------------------------- mailables


class WelcomeMailable(Mailable):
    def __init__(self, recipient: str, name: str) -> None:
        self.recipient = recipient
        self.name = name

    async def build(self) -> Message:
        return Message(
            to=(self.recipient,),
            subject=f"Welcome, {self.name}",
            html=f"<p>Hi {self.name}, welcome aboard.</p>",
            text=f"Hi {self.name}, welcome aboard.",
        )


class EmptyMailable(Mailable):
    async def build(self) -> Message:
        return Message(to=("x@y",), subject="empty")


class BrokenMailable(Mailable):
    async def build(self) -> Message:
        return "not a message"  # type: ignore[return-value]


# ------------------------------------------------------------------- transport


async def test_memory_transport_captures_messages() -> None:
    transport = MemoryTransport()
    mailer = Mailer(transport, default_from="noreply@example.com")
    await mailer.send(WelcomeMailable("alice@example.com", "Alice"))

    sent = transport.sent
    assert len(sent) == 1
    assert sent[0].to == ("alice@example.com",)
    assert sent[0].subject == "Welcome, Alice"
    assert sent[0].from_address == "noreply@example.com"


async def test_memory_transport_rejects_empty_body() -> None:
    transport = MemoryTransport()
    mailer = Mailer(transport)
    with pytest.raises(TransportError, match="empty body"):
        await mailer.send(EmptyMailable())


async def test_log_transport_writes_to_logger(
    caplog: pytest.LogCaptureFixture,
) -> None:
    transport = LogTransport(logging.getLogger("pylar.mail"))
    mailer = Mailer(transport)
    with caplog.at_level(logging.INFO, logger="pylar.mail"):
        await mailer.send(WelcomeMailable("bob@example.com", "Bob"))
    assert any("Welcome, Bob" in r.message for r in caplog.records)


def test_memory_transport_satisfies_protocol() -> None:
    assert isinstance(MemoryTransport(), Transport)


# ----------------------------------------------------------------- mailer rules


async def test_mailer_fills_default_from_when_missing() -> None:
    transport = MemoryTransport()
    mailer = Mailer(transport, default_from="hello@example.com")
    await mailer.send(WelcomeMailable("a@b", "A"))
    assert transport.sent[0].from_address == "hello@example.com"


async def test_mailer_keeps_explicit_from_address() -> None:
    transport = MemoryTransport()
    mailer = Mailer(transport, default_from="default@example.com")

    class ExplicitFromMailable(Mailable):
        async def build(self) -> Message:
            return Message(
                to=("a@b",),
                subject="x",
                text="y",
                **{"from": "custom@example.com"},  # alias
            )

    await mailer.send(ExplicitFromMailable())
    assert transport.sent[0].from_address == "custom@example.com"


async def test_mailer_rejects_non_message_returns() -> None:
    transport = MemoryTransport()
    mailer = Mailer(transport)
    with pytest.raises(MailableDefinitionError, match="must return a Message"):
        await mailer.send(BrokenMailable())


# ---------------------------------------------------------------- attachments


async def test_message_carries_attachments() -> None:
    transport = MemoryTransport()
    mailer = Mailer(transport)

    class WithAttachment(Mailable):
        async def build(self) -> Message:
            return Message(
                to=("a@b",),
                subject="file",
                text="see attached",
                attachments=(
                    Attachment(
                        filename="hello.txt",
                        content=b"hi there",
                        content_type="text/plain",
                    ),
                ),
            )

    await mailer.send(WithAttachment())
    assert len(transport.sent[0].attachments) == 1
    assert transport.sent[0].attachments[0].filename == "hello.txt"
    assert transport.sent[0].attachments[0].content == b"hi there"


def test_smtp_transport_builds_email_with_attachment() -> None:
    from pylar.mail.drivers.smtp import SmtpTransport

    msg = Message(
        to=("a@b",),
        subject="file",
        text="body",
        attachments=(
            Attachment(
                filename="hello.txt",
                content=b"hi there",
                content_type="text/plain",
            ),
        ),
    )
    em = SmtpTransport._build_email(msg)
    parts = list(em.iter_attachments())
    assert len(parts) == 1
    assert parts[0].get_filename() == "hello.txt"
    assert parts[0].get_content_type() == "text/plain"


def test_smtp_transport_builds_inline_attachment_with_cid() -> None:
    from pylar.mail.drivers.smtp import SmtpTransport

    msg = Message(
        to=("a@b",),
        subject="hi",
        html='<img src="cid:logo">',
        attachments=(
            Attachment(
                filename="logo.png",
                content=b"\x89PNG",
                content_type="image/png",
                inline=True,
                cid="logo",
            ),
        ),
    )
    em = SmtpTransport._build_email(msg)
    # Inline attachments live under related iteration, but add_attachment
    # with disposition=inline still surfaces them; the CID header must
    # reflect our request.
    cids = [
        part["Content-ID"]
        for part in em.walk()
        if part.get("Content-ID") is not None
    ]
    assert "<logo>" in cids


# -------------------------------------------------------------- ViewMailable


@pytest.fixture
def view(tmp_path: Path) -> View:
    (tmp_path / "welcome.html").write_text(
        "<h1>Hello {{ name }}</h1><p>Welcome aboard.</p>"
    )
    (tmp_path / "welcome.txt").write_text("Hello {{ name }}\nWelcome aboard.")
    return View(JinjaRenderer(tmp_path, autoescape=False))


async def test_view_mailable_renders_html_and_text(view: View) -> None:
    class Welcome(ViewMailable):
        html_template = "welcome.html"
        text_template = "welcome.txt"

        def __init__(self, view: View, *, to: str, name: str) -> None:
            super().__init__(view)
            self._to = to
            self._name = name

        def recipients(self) -> tuple[str, ...]:
            return (self._to,)

        def subject(self) -> str:
            return f"Welcome, {self._name}"

        def context(self) -> dict[str, object]:
            return {"name": self._name}

    transport = MemoryTransport()
    mailer = Mailer(transport)
    await mailer.send(Welcome(view, to="a@b", name="Alice"))

    sent = transport.sent[0]
    assert sent.subject == "Welcome, Alice"
    assert sent.html is not None and "Hello Alice" in sent.html
    assert sent.text is not None and "Hello Alice" in sent.text


async def test_view_mailable_derives_text_from_html_when_only_html_set(
    view: View,
) -> None:
    class HtmlOnly(ViewMailable):
        html_template = "welcome.html"

        def recipients(self) -> tuple[str, ...]:
            return ("a@b",)

        def subject(self) -> str:
            return "x"

        def context(self) -> dict[str, object]:
            return {"name": "Bob"}

    transport = MemoryTransport()
    mailer = Mailer(transport)
    await mailer.send(HtmlOnly(view))

    sent = transport.sent[0]
    assert sent.html is not None and "<h1>" in sent.html
    # Tags stripped in the fallback text body.
    assert sent.text is not None and "<" not in sent.text
    assert "Hello Bob" in sent.text


async def test_view_mailable_requires_at_least_one_template(view: View) -> None:
    class Empty(ViewMailable):
        def recipients(self) -> tuple[str, ...]:
            return ("a@b",)

        def subject(self) -> str:
            return "x"

    mailer = Mailer(MemoryTransport())
    with pytest.raises(NotImplementedError, match="html_template"):
        await mailer.send(Empty(view))


# ------------------------------------------------------------ MarkdownMailable


async def test_markdown_mailable_renders_html_and_keeps_source_as_text() -> None:
    class Announce(MarkdownMailable):
        def recipients(self) -> tuple[str, ...]:
            return ("a@b",)

        def subject(self) -> str:
            return "News"

        def markdown(self) -> str:
            return "# Heading\n\nHello **world**."

    transport = MemoryTransport()
    mailer = Mailer(transport)
    await mailer.send(Announce())

    sent = transport.sent[0]
    assert sent.html is not None
    assert "<h1>" in sent.html and "<strong>world</strong>" in sent.html
    assert sent.text == "# Heading\n\nHello **world**."


# -------------------------------------------------------------- mailer.queue


class WelcomePayload(JobPayload):
    recipient: str
    name: str


class QueueableWelcome(Mailable):
    payload_type: ClassVar[type[JobPayload] | None] = WelcomePayload

    def __init__(self, *, recipient: str, name: str) -> None:
        self._recipient = recipient
        self._name = name

    async def build(self) -> Message:
        return Message(
            to=(self._recipient,),
            subject=f"Welcome, {self._name}",
            text=f"Hi {self._name}",
        )

    def to_payload(self) -> JobPayload:
        return WelcomePayload(recipient=self._recipient, name=self._name)

    @classmethod
    def from_payload(cls, container: Container, payload: JobPayload) -> Self:
        assert isinstance(payload, WelcomePayload)
        return cls(recipient=payload.recipient, name=payload.name)


async def test_mailer_queue_dispatches_send_mailable_job() -> None:
    transport = MemoryTransport()
    dispatcher = Dispatcher.fake()
    mailer = Mailer(transport, dispatcher=dispatcher)

    await mailer.queue(QueueableWelcome(recipient="a@b", name="Alice"))

    dispatched = dispatcher.dispatched(SendMailableJob)
    assert len(dispatched) == 1
    payload = dispatched[0]
    assert isinstance(payload, SendMailablePayload)
    assert "QueueableWelcome" in payload.mailable_class
    assert "WelcomePayload" in payload.payload_type


async def test_mailer_queue_without_dispatcher_raises() -> None:
    mailer = Mailer(MemoryTransport())
    with pytest.raises(MailableDefinitionError, match="Dispatcher"):
        await mailer.queue(QueueableWelcome(recipient="a@b", name="A"))


async def test_mailer_queue_requires_queueable_mailable() -> None:
    mailer = Mailer(MemoryTransport(), dispatcher=Dispatcher.fake())
    with pytest.raises(MailableDefinitionError, match="not queueable"):
        await mailer.queue(WelcomeMailable("a@b", "A"))


async def test_send_mailable_job_rebuilds_and_sends() -> None:
    transport = MemoryTransport()
    mailer = Mailer(transport)
    container = Container()

    job = SendMailableJob(container, mailer)
    inner = WelcomePayload(recipient="c@d", name="Carol")
    payload = SendMailablePayload(
        mailable_class=f"{QueueableWelcome.__module__}.{QueueableWelcome.__qualname__}",
        payload_type=f"{WelcomePayload.__module__}.{WelcomePayload.__qualname__}",
        payload_json=inner.model_dump_json(),
    )
    await job.handle(payload)

    assert len(transport.sent) == 1
    assert transport.sent[0].to == ("c@d",)
    assert transport.sent[0].subject == "Welcome, Carol"


async def test_send_mailable_job_round_trip_through_real_queue() -> None:
    """End-to-end: mailer.queue → queue → worker → transport."""
    from pylar.queue import Worker

    transport = MemoryTransport()
    queue = MemoryQueue()
    dispatcher = Dispatcher(queue)
    container = Container()
    mailer = Mailer(transport, dispatcher=dispatcher)
    container.instance(Mailer, mailer)
    container.instance(Container, container)

    await mailer.queue(QueueableWelcome(recipient="e@f", name="Eve"))

    worker = Worker(queue, container)
    ran = await worker.process_next(timeout=0.01)
    assert ran is True
    assert len(transport.sent) == 1
    assert transport.sent[0].to == ("e@f",)
