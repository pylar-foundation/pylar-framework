"""Service provider that wires the i18n layer."""

from __future__ import annotations

from pylar.foundation.container import Container
from pylar.foundation.provider import ServiceProvider
from pylar.i18n.config import I18nConfig
from pylar.i18n.loader import TranslationLoader
from pylar.i18n.translator import Translator


class I18nServiceProvider(ServiceProvider):
    """Bind a :class:`Translator` populated from ``resources/lang``.

    The provider reads :class:`I18nConfig` from the container if the
    user supplied one; otherwise it falls back to the conventional
    English defaults. Translation files are loaded eagerly during
    ``register`` so the catalogues are available before any other
    provider's ``boot`` runs.
    """

    def register(self, container: Container) -> None:
        if self.app.container.has(I18nConfig):
            config = self.app.container.make(I18nConfig)
            translator = Translator(
                default_locale=config.default,
                fallback_locale=config.fallback,
            )
        else:
            translator = Translator()

        loader = TranslationLoader(self.app.base_path / "resources" / "lang")
        for locale, messages in loader.load().items():
            translator.add_messages(locale, messages)

        container.singleton(Translator, lambda: translator)
