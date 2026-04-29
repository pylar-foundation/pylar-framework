"""Typed console layer: Command base, ConsoleKernel, ``pylar`` entrypoint."""

from pylar.console.command import Command
from pylar.console.exceptions import (
    ArgumentParseError,
    CommandDefinitionError,
    CommandNotFoundError,
    ConsoleError,
)
from pylar.console.kernel import COMMANDS_TAG, ConsoleKernel
from pylar.console.output import BufferedOutput, Output, OutputWriter

__all__ = [
    "COMMANDS_TAG",
    "ArgumentParseError",
    "BufferedOutput",
    "Command",
    "CommandDefinitionError",
    "CommandNotFoundError",
    "ConsoleError",
    "ConsoleKernel",
    "Output",
    "OutputWriter",
]
