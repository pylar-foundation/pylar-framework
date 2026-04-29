"""The :class:`ViewRenderer` Protocol — every template engine implements it."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ViewRenderer(Protocol):
    """Render a named template against a context dict to a string of bytes-of-text.

    Pylar ships with one implementation, :class:`JinjaRenderer`, but the
    Protocol is the sole dependency of the :class:`View` facade so that
    alternative engines (Mako, Chameleon) can drop in by binding their
    own implementation.
    """

    async def render(self, template: str, context: dict[str, Any]) -> str: ...
