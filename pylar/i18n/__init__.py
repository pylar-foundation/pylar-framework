"""Typed translation layer with JSON catalogues and ambient locale."""

from pylar.i18n.config import I18nConfig
from pylar.i18n.context import current_locale, with_locale
from pylar.i18n.exceptions import I18nError, TranslationLoadError
from pylar.i18n.loader import TranslationLoader
from pylar.i18n.middleware import AcceptLanguageMiddleware, LocalePrefixMiddleware
from pylar.i18n.provider import I18nServiceProvider
from pylar.i18n.translator import Translator

__all__ = [
    "AcceptLanguageMiddleware",
    "I18nConfig",
    "I18nError",
    "I18nServiceProvider",
    "LocalePrefixMiddleware",
    "TranslationLoadError",
    "TranslationLoader",
    "Translator",
    "current_locale",
    "with_locale",
]
