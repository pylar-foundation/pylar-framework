"""Exceptions raised by the console layer."""

from __future__ import annotations


class ConsoleError(Exception):
    """Base class for console errors."""


class CommandNotFoundError(ConsoleError):
    """Raised when no registered command matches the requested name."""


class CommandDefinitionError(ConsoleError):
    """Raised when a Command subclass is malformed (missing name, bad input type, ...)."""


class ArgumentParseError(ConsoleError):
    """Raised when argv cannot be parsed against a command's input dataclass."""
