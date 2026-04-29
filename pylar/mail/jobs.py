"""Generic queue job that rebuilds and delivers a :class:`Mailable`."""

from __future__ import annotations

import importlib
from typing import ClassVar

from pylar.foundation.container import Container
from pylar.mail.exceptions import MailableDefinitionError
from pylar.mail.mailable import Mailable
from pylar.mail.mailer import Mailer
from pylar.queue.job import Job
from pylar.queue.payload import JobPayload


class SendMailablePayload(JobPayload):
    """Wire format for a queued :class:`Mailable` dispatch.

    *mailable_class* is the fully qualified name of the Mailable
    subclass. *payload_type* is the fully qualified name of its
    :class:`JobPayload` subclass. *payload_json* is that payload
    serialised to JSON. The worker resolves the class, revives the
    payload, hands it to :meth:`Mailable.from_payload`, and then asks
    the bound :class:`Mailer` to send the resulting mailable.
    """

    mailable_class: str
    payload_type: str
    payload_json: str


class SendMailableJob(Job[SendMailablePayload]):
    """The generic queue entry point for :meth:`Mailer.queue`."""

    payload_type: ClassVar[type[JobPayload]] = SendMailablePayload

    def __init__(self, container: Container, mailer: Mailer) -> None:
        self._container = container
        self._mailer = mailer

    async def handle(self, payload: SendMailablePayload) -> None:
        mailable_cls = self._resolve(payload.mailable_class, Mailable)  # type: ignore[type-abstract]
        payload_cls = self._resolve(payload.payload_type, JobPayload)
        inner = payload_cls.model_validate_json(payload.payload_json)
        mailable = mailable_cls.from_payload(self._container, inner)
        await self._mailer.send(mailable)

    @staticmethod
    def _resolve[T](qualified_name: str, base: type[T]) -> type[T]:
        module_name, _, class_name = qualified_name.rpartition(".")
        if not module_name or not class_name:
            raise MailableDefinitionError(
                f"{qualified_name!r} is not a fully qualified name"
            )
        module = importlib.import_module(module_name)
        obj = getattr(module, class_name, None)
        if not isinstance(obj, type) or not issubclass(obj, base):
            raise MailableDefinitionError(
                f"{qualified_name} resolved to {obj!r}, "
                f"which is not a {base.__qualname__} subclass"
            )
        return obj
