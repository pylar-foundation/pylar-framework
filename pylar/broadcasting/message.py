"""Typed broadcast message base.

A :class:`BroadcastMessage` is a pydantic-frozen payload that is
validated before publishing and serialised as JSON on the wire::

    class OrderShipped(BroadcastMessage):
        order_id: int
        eta: str

    await broadcaster.publish("orders", OrderShipped(order_id=1, eta="2h").to_dict())
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class BroadcastMessage(BaseModel):
    """Strict, frozen base for typed broadcast payloads."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dict suitable for :meth:`Broadcaster.publish`."""
        return self.model_dump()
