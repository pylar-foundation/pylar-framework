"""The :class:`Mailable` base class — describes one outgoing email."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from html import unescape
from typing import TYPE_CHECKING, Any, ClassVar, Self

from pylar.mail.message import Message
from pylar.queue.payload import JobPayload
from pylar.views.view import View

if TYPE_CHECKING:
    from pylar.foundation.container import Container


class Mailable(ABC):
    """A typed builder for one email.

    Subclasses receive their dependencies through ``__init__`` (the mailer
    constructs them via the container) and implement :meth:`build` to
    return a fully populated :class:`Message`. Templating, branding, and
    any per-tenant customisation lives inside the build method, leaving
    the :class:`Mailer` and the transport drivers oblivious to it.

    Queueable mailables additionally declare a ``payload_type`` class
    attribute and implement :meth:`to_payload` / :meth:`from_payload`.
    The :class:`Mailer.queue` path uses those two hooks to move the
    mailable across the wire through a generic :class:`SendMailableJob`,
    so slow SMTP relays never block request handlers.
    """

    #: Optional: declare the :class:`JobPayload` subclass this mailable
    #: serialises to when queued. Required only if the mailable is
    #: dispatched through :meth:`Mailer.queue`.
    payload_type: ClassVar[type[JobPayload] | None] = None

    @abstractmethod
    async def build(self) -> Message:
        """Render and return the message ready for delivery."""

    def to_payload(self) -> JobPayload:
        """Serialise the mailable's state into a :class:`JobPayload`.

        Override alongside :meth:`from_payload` on any mailable that
        should be dispatched through :meth:`Mailer.queue`.
        """
        raise NotImplementedError(
            f"{type(self).__qualname__} does not support queuing — "
            "override to_payload/from_payload to opt in."
        )

    @classmethod
    def from_payload(cls, container: Container, payload: JobPayload) -> Self:
        """Reconstruct the mailable from a :class:`JobPayload`.

        *container* is provided so the mailable can pull its runtime
        dependencies (typically a :class:`View`) out of the container
        while state-carrying fields come from *payload*.
        """
        raise NotImplementedError(
            f"{cls.__qualname__} does not support queuing — "
            "override to_payload/from_payload to opt in."
        )


class ViewMailable(Mailable):
    """A :class:`Mailable` that renders its bodies from Jinja templates.

    Subclasses set the recipient / subject / template names on the
    instance and override :meth:`context` to provide the dict handed to
    the template renderer. The view layer lives behind the container —
    pylar binds a :class:`View` singleton as part of its default
    providers — so subclasses receive it via ``__init__``::

        class InvoiceMailable(ViewMailable):
            html_template = "mail/invoice.html"
            text_template = "mail/invoice.txt"

            def __init__(self, view: View, *, to: str, invoice: Invoice) -> None:
                super().__init__(view)
                self._to = to
                self._invoice = invoice

            def recipients(self) -> tuple[str, ...]:
                return (self._to,)

            def subject(self) -> str:
                return f"Invoice #{self._invoice.number}"

            def context(self) -> dict[str, object]:
                return {"invoice": self._invoice}

    Either ``html_template`` or ``text_template`` (or both) must be set.
    When only the HTML template is declared the plain-text body is
    derived automatically via a best-effort tag strip so clients without
    HTML rendering still receive readable content.
    """

    html_template: str | None = None
    text_template: str | None = None

    def __init__(self, view: View) -> None:
        self._view = view

    # ---- hooks a subclass fills in --------------------------------------

    def recipients(self) -> tuple[str, ...]:
        raise NotImplementedError

    def subject(self) -> str:
        raise NotImplementedError

    def context(self) -> dict[str, Any]:
        return {}

    def attachments(self) -> tuple[Any, ...]:
        return ()

    # ---- build ----------------------------------------------------------

    async def build(self) -> Message:
        if self.html_template is None and self.text_template is None:
            raise NotImplementedError(
                f"{type(self).__qualname__} must set html_template and/or text_template"
            )
        ctx = self.context()
        html: str | None = None
        text: str | None = None
        if self.html_template is not None:
            html = await self._view.render(self.html_template, ctx)
        if self.text_template is not None:
            text = await self._view.render(self.text_template, ctx)
        elif html is not None:
            text = self._strip_html(html)
        return Message(
            to=self.recipients(),
            subject=self.subject(),
            html=html,
            text=text,
            attachments=tuple(self.attachments()),
        )

    @staticmethod
    def _strip_html(html: str) -> str:
        """Coarse tag-strip fallback for text-only clients."""
        no_tags = re.sub(r"<[^>]+>", "", html)
        collapsed = re.sub(r"\s+\n", "\n", no_tags)
        return unescape(collapsed).strip()


class MarkdownMailable(Mailable):
    """A :class:`Mailable` rendered from a Markdown source.

    Override :meth:`markdown` to return the Markdown body and set the
    recipient / subject through the same hooks as :class:`ViewMailable`.
    The HTML body is produced via the ``markdown`` package (install
    through the ``pylar[mail-markdown]`` extra) and the plain-text body
    is the Markdown source itself — which already reads well on its own,
    which is the whole point of Markdown.
    """

    def __init__(self) -> None:  # pragma: no cover - trivial
        pass

    def recipients(self) -> tuple[str, ...]:
        raise NotImplementedError

    def subject(self) -> str:
        raise NotImplementedError

    def markdown(self) -> str:
        raise NotImplementedError

    def attachments(self) -> tuple[Any, ...]:
        return ()

    async def build(self) -> Message:
        source = self.markdown()
        html = self._render_html(source)
        return Message(
            to=self.recipients(),
            subject=self.subject(),
            html=html,
            text=source,
            attachments=tuple(self.attachments()),
        )

    @staticmethod
    def _render_html(source: str) -> str:
        try:
            import markdown as _markdown
        except ImportError as exc:  # pragma: no cover - dependency missing
            raise RuntimeError(
                "MarkdownMailable requires the 'markdown' package. Install "
                "the pylar[mail-markdown] extra."
            ) from exc
        return str(_markdown.markdown(source, extensions=["extra"]))
