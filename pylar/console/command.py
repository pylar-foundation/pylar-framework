"""Base class for every CLI command in pylar."""

from __future__ import annotations

import argparse
from abc import ABC, abstractmethod
from typing import Any, ClassVar, cast

from pylar.console.exceptions import CommandDefinitionError
from pylar.console.input import build_parser, parse_args


class Command[InputT](ABC):
    """A typed CLI command.

    Subclasses declare:

    * ``name`` — the dotted name used on the command line (``make:model``).
    * ``description`` — one-line summary shown in ``pylar list``.
    * ``input_type`` — a frozen dataclass that describes the command's input.

    The command's own ``__init__`` is auto-wired by the container, so it can
    take services as constructor parameters. Runtime values supplied by the
    user on the command line arrive in :meth:`handle` as a single ``input``
    instance — never as ``**kwargs``.

    Example::

        @dataclass(frozen=True)
        class GreetInput:
            target: str
            shout: bool = False

        class GreetCommand(Command[GreetInput]):
            name = "greet"
            description = "Greet someone"
            input_type = GreetInput

            def __init__(self, logger: Logger) -> None:
                self.logger = logger

            async def handle(self, input: GreetInput) -> int:
                message = f"hello {input.target}"
                if input.shout:
                    message = message.upper()
                self.logger.info(message)
                return 0
    """

    name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    input_type: ClassVar[type[Any]]

    @abstractmethod
    async def handle(self, input: InputT) -> int:
        """Run the command and return a process exit code."""

    # ------------------------------------------------------------------ helpers

    @classmethod
    def parser(cls) -> argparse.ArgumentParser:
        cls._validate_definition()
        return build_parser(
            cls.input_type,
            prog=cls.name,
            description=cls.description,
        )

    @classmethod
    def parse(cls, argv: list[str]) -> InputT:
        cls._validate_definition()
        return cast(InputT, parse_args(cls.input_type, cls.parser(), argv))

    @classmethod
    def _validate_definition(cls) -> None:
        if not cls.name:
            raise CommandDefinitionError(
                f"{cls.__qualname__} must define a non-empty `name` class attribute"
            )
        if not hasattr(cls, "input_type"):
            raise CommandDefinitionError(
                f"{cls.__qualname__} must define an `input_type` class attribute"
            )
