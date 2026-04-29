"""Exceptions raised by the config layer."""

from __future__ import annotations


class ConfigError(Exception):
    """Base class for configuration errors."""


class ConfigLoadError(ConfigError):
    """Raised when a config module is malformed or cannot be imported."""


class EnvError(ConfigError):
    """Raised when an environment variable is missing or cannot be parsed."""
