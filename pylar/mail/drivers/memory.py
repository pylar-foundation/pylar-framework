"""In-process mail transport — used by tests and dry-run flows."""

from __future__ import annotations

from pylar.mail.exceptions import TransportError
from pylar.mail.message import Message


class MemoryTransport:
    """Captures every sent message into an in-memory list."""

    def __init__(self) -> None:
        self._sent: list[Message] = []

    async def send(self, message: Message) -> None:
        if not message.has_body():
            raise TransportError(
                f"Refusing to send message to {message.to!r} with empty body"
            )
        self._sent.append(message)

    @property
    def sent(self) -> list[Message]:
        """Every message captured so far. Test affordance."""
        return list(self._sent)

    def clear(self) -> None:
        self._sent.clear()
