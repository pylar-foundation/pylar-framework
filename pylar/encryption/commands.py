"""``pylar key:generate`` — create a fresh APP_KEY."""

from __future__ import annotations

from dataclasses import dataclass

from pylar.console.command import Command
from pylar.console.output import Output
from pylar.encryption.encrypter import Encrypter


@dataclass(frozen=True)
class _KeyGenInput:
    """No arguments."""


class KeyGenerateCommand(Command[_KeyGenInput]):
    name = "key:generate"
    description = "Generate a new APP_KEY for encryption"
    input_type = _KeyGenInput

    def __init__(self, output: Output) -> None:
        self.out = output

    async def handle(self, input: _KeyGenInput) -> int:
        key = Encrypter.generate_key()
        self.out.success(key)
        self.out.newline()
        self.out.line("Add this to your .env file as:")
        self.out.line(f"  APP_KEY={key}")
        return 0
