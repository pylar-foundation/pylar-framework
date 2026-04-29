"""Discovers JSON translation files under ``resources/lang``."""

from __future__ import annotations

import json
from pathlib import Path

from pylar.i18n.exceptions import TranslationLoadError


class TranslationLoader:
    """Load nested ``resources/lang/<locale>/<group>.json`` files.

    The on-disk layout is::

        resources/lang/
            en/
                messages.json
                validation.json
            ru/
                messages.json
                validation.json

    Each JSON file is a flat object whose keys become the leaf segment
    of dotted message keys: ``messages.json`` with ``{"welcome": "Hi"}``
    surfaces as the key ``messages.welcome`` in the translator. Nested
    objects produce dotted keys recursively, so::

        {"validation": {"required": "..." }}

    becomes ``validation.required``.
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    def load(self) -> dict[str, dict[str, str]]:
        """Return ``{locale: {dotted_key: message}}`` for everything under root."""
        catalogues: dict[str, dict[str, str]] = {}
        if not self._root.is_dir():
            return catalogues

        for locale_dir in sorted(self._root.iterdir()):
            if not locale_dir.is_dir():
                continue
            locale = locale_dir.name
            messages: dict[str, str] = {}
            for catalogue_file in sorted(
                p
                for ext in ("*.json", "*.yaml", "*.yml")
                for p in locale_dir.glob(ext)
            ):
                group = catalogue_file.stem
                raw_text = catalogue_file.read_text(encoding="utf-8")
                try:
                    if catalogue_file.suffix == ".json":
                        payload = json.loads(raw_text)
                    else:
                        payload = _load_yaml(catalogue_file, raw_text)
                except TranslationLoadError:
                    raise
                except Exception as exc:
                    raise TranslationLoadError(
                        f"Could not parse {catalogue_file}: {exc}"
                    ) from exc
                if not isinstance(payload, dict):
                    raise TranslationLoadError(
                        f"{catalogue_file} must contain an object at the top level"
                    )
                _flatten(payload, prefix=group, into=messages)
            catalogues[locale] = messages
        return catalogues


def _load_yaml(path: Path, raw_text: str) -> object:
    """Load a YAML file, importing pyyaml lazily."""
    try:
        import yaml
    except ImportError:
        raise TranslationLoadError(
            f"YAML catalogue {path} found but PyYAML is not installed. "
            "Install with: pip install 'pylar[i18n-yaml]'"
        ) from None
    return yaml.safe_load(raw_text)


def _flatten(node: dict[str, object], *, prefix: str, into: dict[str, str]) -> None:
    for key, value in node.items():
        composite_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            _flatten(value, prefix=composite_key, into=into)
        elif isinstance(value, str):
            into[composite_key] = value
        else:
            raise TranslationLoadError(
                f"Translation values must be strings or nested objects; "
                f"got {type(value).__name__} at {composite_key!r}"
            )
