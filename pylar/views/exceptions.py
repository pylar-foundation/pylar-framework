"""Exceptions raised by the views layer."""

from __future__ import annotations


class ViewError(Exception):
    """Base class for view-rendering errors."""


class TemplateNotFoundError(ViewError):
    """Raised when the renderer cannot locate the requested template."""

    def __init__(self, template: str) -> None:
        self.template = template
        super().__init__(f"Template not found: {template}")
