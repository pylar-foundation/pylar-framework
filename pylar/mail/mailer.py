"""The :class:`Mailer` facade — controllers depend on this, not on transports."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from pylar.mail.exceptions import MailableDefinitionError
from pylar.mail.mailable import Mailable
from pylar.mail.message import Message
from pylar.mail.transport import Transport

if TYPE_CHECKING:
    from pylar.queue.dispatcher import Dispatcher
    from pylar.queue.record import JobRecord


class Mailer:
    """Build a :class:`Mailable` and hand the result to the bound transport.

    The default *from* address is filled in here when a Mailable returns
    a message with no explicit sender, so individual mailables stay
    free of branding boilerplate. The transport itself only sees fully
    populated :class:`Message` instances.
    """

    def __init__(
        self,
        transport: Transport,
        *,
        default_from: str = "",
        dispatcher: Dispatcher | None = None,
    ) -> None:
        self._transport = transport
        self._default_from = default_from
        self._dispatcher = dispatcher

    async def send(self, mailable: Mailable) -> Message:
        """Build the mailable, fill in the default sender, and dispatch."""
        message = await mailable.build()
        if not isinstance(message, Message):
            raise MailableDefinitionError(
                f"{type(mailable).__qualname__}.build() must return a Message, "
                f"got {type(message).__qualname__}"
            )
        if not message.from_address and self._default_from:
            message = message.model_copy(
                update={"from_address": self._default_from}
            )
        await self._transport.send(message)
        return message

    async def queue(
        self,
        mailable: Mailable,
        *,
        delay: timedelta | None = None,
    ) -> JobRecord:
        """Dispatch *mailable* onto the queue instead of sending inline.

        Requires a :class:`pylar.queue.Dispatcher` to have been bound
        when the mailer was constructed — the service provider does
        this automatically when the queue provider is registered. The
        mailable itself must implement :meth:`Mailable.to_payload` and
        expose a ``payload_type`` class attribute; otherwise the method
        raises :class:`MailableDefinitionError`.
        """
        from pylar.mail.jobs import SendMailableJob, SendMailablePayload

        if self._dispatcher is None:
            raise MailableDefinitionError(
                "Mailer.queue() requires a Dispatcher — bind the queue "
                "service provider or pass dispatcher=... explicitly."
            )
        payload_type = type(mailable).payload_type
        if payload_type is None:
            raise MailableDefinitionError(
                f"{type(mailable).__qualname__} is not queueable — "
                "set payload_type and implement to_payload/from_payload."
            )
        inner = mailable.to_payload()
        if not isinstance(inner, payload_type):
            raise MailableDefinitionError(
                f"{type(mailable).__qualname__}.to_payload() must return "
                f"an instance of {payload_type.__qualname__}, "
                f"got {type(inner).__qualname__}"
            )
        mailable_cls = type(mailable)
        dispatch_payload = SendMailablePayload(
            mailable_class=f"{mailable_cls.__module__}.{mailable_cls.__qualname__}",
            payload_type=f"{payload_type.__module__}.{payload_type.__qualname__}",
            payload_json=inner.model_dump_json(),
        )
        return await self._dispatcher.dispatch(
            SendMailableJob, dispatch_payload, delay=delay
        )

    @staticmethod
    def fake() -> Any:
        """Return a recording :class:`FakeMailer` for tests.

        Drop-in for :class:`Mailer` — controllers under test that
        declare ``mailer: Mailer`` in their ``__init__`` accept the
        fake without changes when the test binds it via
        ``container.instance(Mailer, Mailer.fake())``.
        """
        from pylar.testing.fakes import FakeMailer

        return FakeMailer()
