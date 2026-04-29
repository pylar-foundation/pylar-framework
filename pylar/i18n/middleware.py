"""HTTP middleware that picks the request locale from ``Accept-Language``."""

from __future__ import annotations

from pylar.http.middleware import RequestHandler
from pylar.http.request import Request
from pylar.http.response import Response
from pylar.i18n.context import with_locale
from pylar.i18n.translator import Translator


class AcceptLanguageMiddleware:
    """Resolve the request locale and install it via :func:`with_locale`.

    The middleware reads the standard ``Accept-Language`` header,
    parses the comma-separated list with quality factors, and picks
    the highest-priority entry that the bound :class:`Translator`
    actually has a catalogue for. If no acceptable locale matches the
    middleware falls back to the translator's default — which keeps
    the request alive instead of bouncing the user with a 406.

    Mirrors :class:`pylar.database.DatabaseSessionMiddleware` and
    :class:`pylar.auth.AuthMiddleware`: it does not enforce anything,
    only binds an ambient context variable that controllers and
    templates downstream can read through :func:`current_locale`.
    """

    def __init__(self, translator: Translator) -> None:
        self._translator = translator

    async def handle(
        self, request: Request, next_handler: RequestHandler
    ) -> Response:
        header = request.headers.get("accept-language", "")
        locale = self._negotiate(header)
        with with_locale(locale):
            return await next_handler(request)

    # ------------------------------------------------------------------ internals

    def _negotiate(self, header: str) -> str:
        supported = set(self._translator.locales())
        if not supported:
            return self._default()
        candidates = _parse_accept_language(header)
        for candidate, _quality in candidates:
            if candidate in supported:
                return candidate
            base = candidate.split("-", 1)[0]
            if base in supported:
                return base
        return self._default()

    def _default(self) -> str:
        # Translator does not expose the default directly; mirror the
        # field name to keep the contract narrow.
        return getattr(self._translator, "_default_locale", "en")


class LocalePrefixMiddleware:
    """Resolve the locale from a URL prefix like ``/en/...`` or ``/ru/...``.

    The middleware strips the locale segment from ``request.scope["path"]``
    before delegating so downstream routes do not need to include it in
    their patterns. If the first segment is not a known locale the
    middleware falls back to the translator's default and leaves the
    path unchanged.

    Attach to the route group that covers your localised pages::

        localised = router.group(middleware=[LocalePrefixMiddleware])
        localised.get("/{locale}/about", AboutController.show)

    Or more commonly, define two groups::

        router.group(prefix="/{locale}", middleware=[LocalePrefixMiddleware])
    """

    def __init__(self, translator: Translator) -> None:
        self._translator = translator

    async def handle(
        self, request: Request, next_handler: RequestHandler
    ) -> Response:
        path: str = request.scope.get("path", "/")
        segments = path.strip("/").split("/", 1)
        candidate = segments[0].lower() if segments[0] else ""
        supported = set(self._translator.locales())

        if candidate in supported:
            locale = candidate
            # Strip the locale prefix from the path for downstream routing.
            remaining = f"/{segments[1]}" if len(segments) > 1 else "/"
            request.scope["path"] = remaining
        else:
            locale = getattr(self._translator, "_default_locale", "en")

        with with_locale(locale):
            return await next_handler(request)


def _parse_accept_language(header: str) -> list[tuple[str, float]]:
    """Parse a comma-separated Accept-Language header into ``(locale, q)`` pairs.

    Returns the entries sorted by quality factor (descending). Invalid
    or empty entries are silently dropped — clients send weird
    Accept-Language headers all the time and pylar prefers serving
    the request to throwing up its hands.
    """
    entries: list[tuple[str, float]] = []
    for raw in header.split(","):
        raw = raw.strip()
        if not raw:
            continue
        if ";" in raw:
            tag, _, params = raw.partition(";")
            tag = tag.strip().lower()
            quality = 1.0
            for param in params.split(";"):
                param = param.strip()
                if param.startswith("q="):
                    try:
                        quality = float(param[2:])
                    except ValueError:
                        quality = 0.0
        else:
            tag = raw.lower()
            quality = 1.0
        if tag and quality > 0:
            entries.append((tag, quality))
    entries.sort(key=lambda pair: pair[1], reverse=True)
    return entries
