"""High-level view facade — turns a template name into an HtmlResponse."""

from __future__ import annotations

from typing import Any

from pylar.http.response import HtmlResponse
from pylar.views.renderer import ViewRenderer


class View:
    """Convenience wrapper around :class:`ViewRenderer`.

    Controllers depend on ``View`` instead of the renderer directly so
    they can return a ready-to-serve response in a single line::

        async def index(self, request: Request) -> Response:
            return await self.views.make("home.html", {"name": "world"})

    The view also exposes a small *shared context* mechanism: values
    registered via :meth:`share` are merged into every render so that
    layout-wide data (the current user, app version, feature flags)
    does not have to be threaded through every controller. The View
    instance is bound to the application container as a singleton, so
    shared values persist for the lifetime of the process — which is
    typically what you want for layout globals. For *per-request*
    extras, use :meth:`with_` to derive a fresh View bound to one
    additional context dict without mutating the singleton.
    """

    def __init__(self, renderer: ViewRenderer) -> None:
        self._renderer = renderer
        self._shared: dict[str, Any] = {}

    def share(self, key: str, value: Any) -> None:
        """Register *value* under *key* as a global available in every render.

        Process-wide. Useful for app-version banners, feature flag
        snapshots, and similar layout globals. Per-request data should
        use :meth:`with_` instead so it does not leak across users.
        """
        self._shared[key] = value

    def with_(self, extras: dict[str, Any]) -> View:
        """Return a new View whose renders also include *extras*.

        The returned instance shares the same renderer and shared
        bag as the original — only the per-call extras are layered
        on top. The original View is not mutated, so different
        request scopes can derive their own children safely.
        """
        clone = View(self._renderer)
        clone._shared = {**self._shared, **extras}
        return clone

    async def render(self, template: str, context: dict[str, Any] | None = None) -> str:
        """Return the rendered template body as a string."""
        merged = self._merge(context)
        return await self._renderer.render(template, merged)

    async def make(
        self,
        template: str,
        context: dict[str, Any] | None = None,
        *,
        status: int = 200,
    ) -> HtmlResponse:
        """Render *template* and wrap it in an :class:`HtmlResponse`."""
        body = await self.render(template, context)
        return HtmlResponse(content=body, status_code=status)

    def _merge(self, context: dict[str, Any] | None) -> dict[str, Any]:
        if not self._shared and not context:
            return {}
        if not self._shared:
            return dict(context or {})
        if not context:
            return dict(self._shared)
        return {**self._shared, **context}
