"""The :class:`Translator` — typed message lookup with placeholder substitution."""

from __future__ import annotations

from pylar.i18n.context import current_locale


class Translator:
    """Resolves translation keys against the bound message catalogues.

    Lookup order for ``get(key)``:

    1. The locale supplied as the keyword argument, if any.
    2. The current ambient locale set by :func:`with_locale`.
    3. The translator's own ``default_locale``.
    4. The translator's ``fallback_locale``.
    5. The key itself, returned verbatim.

    The fallback chain stops as soon as a hit is found. Returning the
    raw key as the final fallback is deliberate: it makes missing
    translations visible without crashing the request, which is far
    more useful in development than a runtime error.

    Placeholder substitution uses ``{name}`` syntax — Python's
    ``str.format`` is intentionally **not** used here because format
    syntax is far broader than what users want for translations and
    accidental ``{0}`` / format specs in source strings produce
    confusing errors.
    """

    def __init__(
        self,
        default_locale: str = "en",
        fallback_locale: str = "en",
    ) -> None:
        self._default_locale = default_locale
        self._fallback_locale = fallback_locale
        self._messages: dict[str, dict[str, str]] = {}

    # ----------------------------------------------------------- registration

    def add_messages(self, locale: str, messages: dict[str, str]) -> None:
        """Merge *messages* into the catalogue for *locale*."""
        self._messages.setdefault(locale, {}).update(messages)

    def has(self, key: str, *, locale: str | None = None) -> bool:
        """Return ``True`` when *key* exists in the resolved locale's catalogue."""
        target_locale = self._resolve_locale(locale)
        return key in self._messages.get(target_locale, {})

    def locales(self) -> tuple[str, ...]:
        return tuple(self._messages.keys())

    # ----------------------------------------------------------- lookup

    def get(
        self,
        key: str,
        *,
        locale: str | None = None,
        placeholders: dict[str, object] | None = None,
    ) -> str:
        target_locale = self._resolve_locale(locale)

        message = self._messages.get(target_locale, {}).get(key)
        if message is None and target_locale != self._fallback_locale:
            message = self._messages.get(self._fallback_locale, {}).get(key)
        if message is None:
            return key
        if placeholders:
            for placeholder, value in placeholders.items():
                message = message.replace("{" + placeholder + "}", str(value))
        return message

    def choice(
        self,
        key: str,
        count: int,
        *,
        locale: str | None = None,
        placeholders: dict[str, object] | None = None,
    ) -> str:
        """Pick the right pluralisation form for *count*.

        Catalogues store plural forms as sibling keys under a common
        prefix. ``messages.items.zero``, ``messages.items.one``,
        ``messages.items.few``, ``messages.items.many``, and
        ``messages.items.other`` are all valid; the resolver picks the
        category that matches *count* under the active locale's CLDR
        rule and falls back through ``other`` if no matching variant
        exists.

        ``count`` is automatically injected into the placeholders under
        the name ``count`` so translators can interpolate it directly:
        ``"{count} items"``.
        """
        target_locale = self._resolve_locale(locale)
        category = _plural_category(target_locale, count)
        full_placeholders: dict[str, object] = {"count": count, **(placeholders or {})}
        for candidate in (f"{key}.{category}", f"{key}.other"):
            message = self._messages.get(target_locale, {}).get(candidate)
            if message is None and target_locale != self._fallback_locale:
                message = self._messages.get(self._fallback_locale, {}).get(
                    candidate
                )
            if message is not None:
                for placeholder, value in full_placeholders.items():
                    message = message.replace("{" + placeholder + "}", str(value))
                return message
        return key

    # ------------------------------------------------------------------ helpers

    def _resolve_locale(self, explicit: str | None) -> str:
        if explicit is not None:
            return explicit
        ambient = current_locale()
        if ambient is not None:
            return ambient
        return self._default_locale


# --------------------------------------------------------- plural rules


def _plural_category(locale: str, count: int) -> str:
    """Return a CLDR plural category name for *count* under *locale*.

    Pylar implements rules for the major locales it ships docs in
    (English, Russian/Ukrainian/Belarusian, Polish, French, German,
    Spanish) and falls back to the English rule for everything else.
    Real applications that need exact CLDR coverage can replace the
    translator with a Babel-backed implementation.
    """
    base = locale.split("-", 1)[0].split("_", 1)[0].lower()
    rule = _PLURAL_RULES.get(base, _en_plural)
    return rule(count)


def _en_plural(count: int) -> str:
    if count == 0:
        return "zero"
    if count == 1:
        return "one"
    return "other"


def _ru_plural(count: int) -> str:
    mod10 = count % 10
    mod100 = count % 100
    if mod10 == 1 and mod100 != 11:
        return "one"
    if 2 <= mod10 <= 4 and not (12 <= mod100 <= 14):
        return "few"
    if mod10 == 0 or 5 <= mod10 <= 9 or 11 <= mod100 <= 14:
        return "many"
    return "other"


def _pl_plural(count: int) -> str:
    mod10 = count % 10
    mod100 = count % 100
    if count == 1:
        return "one"
    if 2 <= mod10 <= 4 and not (12 <= mod100 <= 14):
        return "few"
    return "many"


def _fr_plural(count: int) -> str:
    if count in (0, 1):
        return "one"
    return "other"


_PLURAL_RULES = {
    "en": _en_plural,
    "de": _en_plural,
    "es": _en_plural,
    "ru": _ru_plural,
    "uk": _ru_plural,
    "be": _ru_plural,
    "pl": _pl_plural,
    "fr": _fr_plural,
}
