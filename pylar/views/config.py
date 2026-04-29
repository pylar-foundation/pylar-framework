"""Typed configuration for the views layer."""

from __future__ import annotations

from pylar.config.schema import BaseConfig


class ViewConfig(BaseConfig):
    """Where templates live and which renderer settings to use.

    ``root`` is the absolute filesystem path that the renderer scans for
    templates. The framework defaults to ``base_path/resources/views`` if
    the user does not override the binding.
    """

    root: str
    autoescape: bool = True
