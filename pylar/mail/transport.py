"""The :class:`Transport` Protocol every mail driver implements."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pylar.mail.message import Message


@runtime_checkable
class Transport(Protocol):
    """Deliver a built :class:`Message` to its recipients.

    The Protocol is intentionally tiny — pylar reserves the right to
    add cancellation hooks, batched sends, and bounce reporting in a
    later iteration, but the minimal contract every driver must satisfy
    is "take a message, deliver it or raise".
    """

    async def send(self, message: Message) -> None: ...
