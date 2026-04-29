"""Typed configuration for the i18n layer."""

from __future__ import annotations

from pylar.config.schema import BaseConfig


class I18nConfig(BaseConfig):
    """Default and fallback locales for the application.

    ``default`` is the locale used when nothing else is specified by the
    request scope. ``fallback`` is the locale consulted when a key is
    missing from the active locale's catalogue — falling back to keeping
    the *key string itself* is intentional, see :class:`Translator`.
    """

    default: str = "en"
    fallback: str = "en"
