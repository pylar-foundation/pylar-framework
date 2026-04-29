"""Commands that the console kernel always registers itself."""

from __future__ import annotations

from dataclasses import dataclass

from pylar.console.command import Command
from pylar.console.output import Output
from pylar.foundation.container import Container


@dataclass(frozen=True)
class _ListInput:
    """No arguments — :class:`ListCommand` lists every registered command."""


class ListCommand(Command[_ListInput]):
    """Built-in ``pylar list`` — prints every registered command."""

    name = "list"
    description = "List all available commands"
    input_type = _ListInput

    def __init__(self, container: Container, output: Output) -> None:
        self.container = container
        self.out = output

    async def handle(self, input: _ListInput) -> int:
        # Local import to avoid a circular dependency between command and kernel.
        from pylar.console.kernel import COMMANDS_TAG

        rows: list[tuple[str, ...]] = []
        for cls in self.container.tagged_types(COMMANDS_TAG):
            cmd_name = getattr(cls, "name", cls.__qualname__)
            description = getattr(cls, "description", "")
            rows.append((cmd_name, description))

        if not rows:
            self.out.info("No commands registered.")
            return 0

        rows.sort(key=lambda row: row[0])
        self.out.table(
            headers=("Command", "Description"),
            rows=rows,
            title="Available Commands",
        )
        return 0


@dataclass(frozen=True)
class _HelpInput:
    command: str = ""


class HelpCommand(Command[_HelpInput]):
    """Built-in ``pylar help <command>`` — prints help for a single command."""

    name = "help"
    description = "Show help for a command"
    input_type = _HelpInput

    def __init__(self, container: Container, output: Output) -> None:
        self.container = container
        self.out = output

    @classmethod
    def parse(cls, argv: list[str]) -> _HelpInput:
        if not argv:
            return _HelpInput()
        return _HelpInput(command=argv[0])

    async def handle(self, input: _HelpInput) -> int:
        from pylar.console.kernel import COMMANDS_TAG

        if not input.command:
            self.out.line("Usage: pylar help <command>")
            self.out.line("Run `pylar list` to see commands.")
            return 0

        for cls in self.container.tagged_types(COMMANDS_TAG):
            if getattr(cls, "name", "") == input.command:
                description = getattr(cls, "description", "")
                self.out.line(f"[accent]{cls.name}[/accent]")
                self.out.line(f"  {description}")
                input_type = getattr(cls, "input_type", None)
                if input_type is not None:
                    fields = getattr(input_type, "__dataclass_fields__", {})
                    if fields:
                        self.out.newline()
                        self.out.line("[label]Arguments:[/label]")
                        for field_name, field_obj in fields.items():
                            self.out.line(f"  {field_name}: {field_obj.type}")
                return 0

        self.out.error(
            f"Unknown command {input.command!r}. Run `pylar list` to see commands."
        )
        return 1
