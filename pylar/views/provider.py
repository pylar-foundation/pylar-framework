"""Service provider that wires the views layer."""

from __future__ import annotations

from pathlib import Path

from pylar.foundation.container import Container
from pylar.foundation.provider import ServiceProvider
from pylar.views.config import ViewConfig
from pylar.views.jinja import JinjaRenderer
from pylar.views.renderer import ViewRenderer
from pylar.views.view import View


class ViewServiceProvider(ServiceProvider):
    """Bind a Jinja2-backed renderer and the :class:`View` facade.

    Reads :class:`ViewConfig` from the container if the user supplied one;
    otherwise falls back to ``base_path/resources/views`` with autoescape
    enabled. The default fits the project layout in ADR-0002 and means
    new projects work out of the box.
    """

    def register(self, container: Container) -> None:
        container.singleton(ViewRenderer, self._make_renderer)  # type: ignore[type-abstract]
        container.singleton(View, self._make_view)

    def _make_renderer(self) -> JinjaRenderer:
        if self.app.container.has(ViewConfig):
            config = self.app.container.make(ViewConfig)
            root = Path(config.root)
            autoescape = config.autoescape
        else:
            root = self.app.base_path / "resources" / "views"
            autoescape = True
        return JinjaRenderer(root, autoescape=autoescape)

    def _make_view(self) -> View:
        renderer = self.app.container.make(ViewRenderer)  # type: ignore[type-abstract]
        return View(renderer)
