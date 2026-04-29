"""Tests for translator.choice() and AcceptLanguageMiddleware."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from pylar.foundation import AppConfig, Application, Container, ServiceProvider
from pylar.http import HttpKernel, Request, Response, json
from pylar.i18n import (
    AcceptLanguageMiddleware,
    Translator,
    current_locale,
)
from pylar.routing import Router

# ---------------------------------------------------------------- choice()


def _trans() -> Translator:
    t = Translator(default_locale="en", fallback_locale="en")
    t.add_messages(
        "en",
        {
            "items.zero": "no items",
            "items.one": "one item",
            "items.other": "{count} items",
        },
    )
    t.add_messages(
        "ru",
        {
            "items.one": "{count} элемент",
            "items.few": "{count} элемента",
            "items.many": "{count} элементов",
        },
    )
    return t


def test_english_zero_one_other() -> None:
    t = _trans()
    assert t.choice("items", 0) == "no items"
    assert t.choice("items", 1) == "one item"
    assert t.choice("items", 5) == "5 items"


def test_russian_one_few_many() -> None:
    t = _trans()
    assert t.choice("items", 1, locale="ru") == "1 элемент"
    assert t.choice("items", 2, locale="ru") == "2 элемента"
    assert t.choice("items", 5, locale="ru") == "5 элементов"
    assert t.choice("items", 21, locale="ru") == "21 элемент"
    assert t.choice("items", 22, locale="ru") == "22 элемента"
    assert t.choice("items", 11, locale="ru") == "11 элементов"


def test_choice_falls_back_to_other_when_category_missing() -> None:
    t = Translator()
    t.add_messages("en", {"items.other": "{count} items"})
    assert t.choice("items", 1) == "1 items"  # one not declared → other


def test_choice_returns_key_when_nothing_matches() -> None:
    t = Translator()
    assert t.choice("missing", 5) == "missing"


def test_choice_supports_extra_placeholders() -> None:
    t = Translator()
    t.add_messages("en", {"items.other": "{user} has {count} items"})
    out = t.choice("items", 5, placeholders={"user": "Alice"})
    assert out == "Alice has 5 items"


# --------------------------------------------------- AcceptLanguageMiddleware


def test_negotiation_picks_best_supported_locale() -> None:
    t = _trans()
    middleware = AcceptLanguageMiddleware(t)
    assert middleware._negotiate("ru,en;q=0.5") == "ru"
    assert middleware._negotiate("fr;q=0.9,en;q=0.8") == "en"
    assert middleware._negotiate("ru-RU,ru;q=0.9") == "ru"


def test_negotiation_falls_back_to_default_when_unsupported() -> None:
    t = _trans()
    middleware = AcceptLanguageMiddleware(t)
    assert middleware._negotiate("ja,zh;q=0.5") == "en"


def test_negotiation_handles_empty_header() -> None:
    t = _trans()
    middleware = AcceptLanguageMiddleware(t)
    assert middleware._negotiate("") == "en"


# -------------------------------------------------- middleware end-to-end


async def _whoami(request: Request) -> Response:
    return json({"locale": current_locale()})


class _Routes(ServiceProvider):
    def register(self, container: Container) -> None:
        translator = _trans()
        container.instance(Translator, translator)

        router = Router()
        group = router.group(middleware=[AcceptLanguageMiddleware])
        group.get("/whoami", _whoami)
        container.singleton(Router, lambda: router)


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = Application(
        base_path=Path("/tmp/pylar-i18n-test"),
        config=AppConfig(
            name="i18n-test",
            debug=True,
            providers=(_Routes,),
        ),
    )
    await app.bootstrap()
    transport = httpx.ASGITransport(app=HttpKernel(app).asgi())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await app.shutdown()


async def test_request_locale_visible_in_handler(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get(
        "/whoami", headers={"Accept-Language": "ru,en;q=0.5"}
    )
    assert response.json()["locale"] == "ru"


async def test_request_falls_back_to_default(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get(
        "/whoami", headers={"Accept-Language": "ja"}
    )
    assert response.json()["locale"] == "en"
