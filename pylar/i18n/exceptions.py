"""Exceptions raised by the i18n layer."""

from __future__ import annotations


class I18nError(Exception):
    """Base class for translation errors."""


class TranslationLoadError(I18nError):
    """Raised when a translation file cannot be parsed."""
