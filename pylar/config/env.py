"""Typed accessors over ``os.environ`` and a minimal ``.env`` file loader.

This module is intentionally tiny. It does not depend on ``pydantic-settings``
because pylar's philosophy is to keep configuration explicit: the user
constructs each config object by hand and reads environment variables through
this typed helper, so the chain from ``.env`` → ``BaseConfig`` instance is
visible in source.

Usage::

    from pylar.config import env

    config = DatabaseConfig(
        host=env.str("DB_HOST", "localhost"),
        port=env.int("DB_PORT", 5432),
        ssl=env.bool("DB_SSL", False),
    )
"""

from __future__ import annotations

import os
from builtins import bool as _bool
from builtins import int as _int
from builtins import str as _str
from pathlib import Path

from pylar.config.exceptions import EnvError

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off", ""})


class Env:
    """Namespace of typed accessors over the process environment.

    Implemented as a class with static methods so that ``env.str``, ``env.int``
    and ``env.bool`` do not collide with the builtin types of the same name
    inside this module.
    """

    @staticmethod
    def str(key: _str, default: _str | None = None) -> _str:
        """Return ``os.environ[key]``, or *default* if absent."""
        value = os.environ.get(key)
        if value is not None:
            return value
        if default is None:
            raise EnvError(
                f"Environment variable {key!r} is not set and no default was provided"
            )
        return default

    @staticmethod
    def int(key: _str, default: _int | None = None) -> _int:
        """Return ``os.environ[key]`` parsed as int, or *default* if absent."""
        raw = os.environ.get(key)
        if raw is None:
            if default is None:
                raise EnvError(
                    f"Environment variable {key!r} is not set and no default was provided"
                )
            return default
        try:
            return _int(raw)
        except ValueError as exc:
            raise EnvError(
                f"Environment variable {key!r} is not a valid int"
            ) from exc

    @staticmethod
    def bool(key: _str, default: _bool | None = None) -> _bool:
        """Return ``os.environ[key]`` parsed as bool, or *default* if absent.

        Recognised true values: ``1``, ``true``, ``yes``, ``on`` (case-insensitive).
        Recognised false values: ``0``, ``false``, ``no``, ``off``, empty string.
        """
        raw = os.environ.get(key)
        if raw is None:
            if default is None:
                raise EnvError(
                    f"Environment variable {key!r} is not set and no default was provided"
                )
            return default
        normalised = raw.strip().lower()
        if normalised in _TRUE_VALUES:
            return True
        if normalised in _FALSE_VALUES:
            return False
        raise EnvError(f"Environment variable {key!r} is not a valid bool")


env = Env


def load_dotenv(path: Path, *, override: bool = False) -> dict[str, str]:
    """Read a ``.env`` file and merge it into ``os.environ``.

    Returns the dict of values that were loaded. When *override* is False
    (the default) variables already present in the environment are kept,
    matching the behaviour Laravel and Django users expect.
    """
    if not path.is_file():
        return {}

    loaded: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise EnvError(f"Malformed line in {path}: {raw_line!r}")
        key, _, value = line.partition("=")
        key = key.strip()
        value = _strip_quotes(value.strip())
        loaded[key] = value
        if override or key not in os.environ:
            os.environ[key] = value
    return loaded


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value
