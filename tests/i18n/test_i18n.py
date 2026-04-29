"""Behavioural tests for the i18n layer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pylar.i18n import (
    TranslationLoader,
    TranslationLoadError,
    Translator,
    current_locale,
    with_locale,
)

# ------------------------------------------------------------------- translator


def _populate(translator: Translator) -> None:
    translator.add_messages(
        "en", {"messages.welcome": "Hello, {name}!", "messages.goodbye": "Bye"}
    )
    translator.add_messages(
        "ru",
        {"messages.welcome": "Привет, {name}!"},
    )


def test_get_returns_translation_for_default_locale() -> None:
    translator = Translator(default_locale="en", fallback_locale="en")
    _populate(translator)
    assert translator.get("messages.welcome", placeholders={"name": "Alice"}) == (
        "Hello, Alice!"
    )


def test_get_uses_explicit_locale_argument() -> None:
    translator = Translator(default_locale="en", fallback_locale="en")
    _populate(translator)
    assert translator.get(
        "messages.welcome", locale="ru", placeholders={"name": "Алиса"}
    ) == "Привет, Алиса!"


def test_get_falls_back_to_fallback_locale() -> None:
    translator = Translator(default_locale="ru", fallback_locale="en")
    _populate(translator)
    # russian catalogue has no goodbye → english fallback returns "Bye"
    assert translator.get("messages.goodbye") == "Bye"


def test_missing_key_returns_key_itself() -> None:
    translator = Translator(default_locale="en", fallback_locale="en")
    _populate(translator)
    assert translator.get("messages.unknown") == "messages.unknown"


def test_ambient_locale_via_with_locale() -> None:
    translator = Translator(default_locale="en", fallback_locale="en")
    _populate(translator)
    assert current_locale() is None
    with with_locale("ru"):
        assert current_locale() == "ru"
        assert translator.get("messages.welcome", placeholders={"name": "X"}) == (
            "Привет, X!"
        )
    assert current_locale() is None


def test_with_locale_nests() -> None:
    translator = Translator(default_locale="en", fallback_locale="en")
    _populate(translator)
    with with_locale("en"):
        with with_locale("ru"):
            assert translator.get(
                "messages.welcome", placeholders={"name": "Y"}
            ) == "Привет, Y!"
        assert translator.get(
            "messages.welcome", placeholders={"name": "Z"}
        ) == "Hello, Z!"


def test_has_reflects_catalogue_membership() -> None:
    translator = Translator(default_locale="en", fallback_locale="en")
    _populate(translator)
    assert translator.has("messages.welcome")
    assert not translator.has("messages.unknown")


def test_placeholder_substitution_with_no_placeholders_keeps_braces() -> None:
    translator = Translator(default_locale="en", fallback_locale="en")
    translator.add_messages("en", {"plain": "{not} substituted"})
    assert translator.get("plain") == "{not} substituted"


# ---------------------------------------------------------------------- loader


def _write(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_loader_returns_empty_for_missing_root(tmp_path: Path) -> None:
    assert TranslationLoader(tmp_path / "missing").load() == {}


def test_loader_flattens_nested_objects(tmp_path: Path) -> None:
    en = tmp_path / "en"
    en.mkdir()
    _write(
        en / "messages.json",
        {"welcome": "Hi", "errors": {"required": "Field is required"}},
    )

    catalogues = TranslationLoader(tmp_path).load()
    assert catalogues == {
        "en": {
            "messages.welcome": "Hi",
            "messages.errors.required": "Field is required",
        }
    }


def test_loader_collects_multiple_locales(tmp_path: Path) -> None:
    (tmp_path / "en").mkdir()
    (tmp_path / "ru").mkdir()
    _write(tmp_path / "en" / "messages.json", {"hi": "Hi"})
    _write(tmp_path / "ru" / "messages.json", {"hi": "Привет"})

    catalogues = TranslationLoader(tmp_path).load()
    assert catalogues["en"]["messages.hi"] == "Hi"
    assert catalogues["ru"]["messages.hi"] == "Привет"


def test_loader_rejects_non_string_leaf(tmp_path: Path) -> None:
    en = tmp_path / "en"
    en.mkdir()
    _write(en / "messages.json", {"count": 42})
    with pytest.raises(TranslationLoadError, match="strings or nested objects"):
        TranslationLoader(tmp_path).load()


def test_loader_rejects_invalid_json(tmp_path: Path) -> None:
    en = tmp_path / "en"
    en.mkdir()
    (en / "messages.json").write_text("{not json}", encoding="utf-8")
    with pytest.raises(TranslationLoadError, match="Could not parse"):
        TranslationLoader(tmp_path).load()


# -------------------------------------------------- YAML catalogues


def test_loader_loads_yaml_catalogue(tmp_path: Path) -> None:
    """YAML .yml/.yaml catalogues are parsed alongside JSON."""
    pytest.importorskip("yaml")
    en = tmp_path / "en"
    en.mkdir()
    (en / "messages.yml").write_text(
        "welcome: Hello\n"
        "nested:\n"
        "  goodbye: Bye\n",
        encoding="utf-8",
    )
    catalogues = TranslationLoader(tmp_path).load()
    assert catalogues["en"]["messages.welcome"] == "Hello"
    assert catalogues["en"]["messages.nested.goodbye"] == "Bye"


def test_loader_mixes_json_and_yaml(tmp_path: Path) -> None:
    """Both JSON and YAML files in the same locale directory are loaded."""
    pytest.importorskip("yaml")
    en = tmp_path / "en"
    en.mkdir()
    _write(en / "messages.json", {"welcome": "Hi"})
    (en / "validation.yaml").write_text(
        "required: This field is required\n",
        encoding="utf-8",
    )
    catalogues = TranslationLoader(tmp_path).load()
    assert catalogues["en"]["messages.welcome"] == "Hi"
    assert catalogues["en"]["validation.required"] == "This field is required"


def test_loader_rejects_invalid_yaml(tmp_path: Path) -> None:
    pytest.importorskip("yaml")
    en = tmp_path / "en"
    en.mkdir()
    (en / "messages.yml").write_text("not: [valid: yaml", encoding="utf-8")
    with pytest.raises(TranslationLoadError, match="Could not parse"):
        TranslationLoader(tmp_path).load()
