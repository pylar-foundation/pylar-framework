"""Typed console output service built on Rich.

Provides a consistent API for all CLI commands: leveled messages,
tables, prompts, progress spinners, and key-value displays. Backed
by Rich's Console for automatic colour detection, markdown rendering,
and beautiful terminal output.

Commands receive an :class:`Output` instance through their typed
``__init__`` like any other dependency::

    class StatusCommand(Command[StatusInput]):
        def __init__(self, output: Output) -> None:
            self.output = output

        async def handle(self, input: StatusInput) -> int:
            self.output.success("All checks passed.")
            return 0

The console kernel binds the default :class:`Output` as a singleton.
Tests use :class:`BufferedOutput` which captures everything to a string.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from io import StringIO
from typing import Protocol, runtime_checkable

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table
from rich.theme import Theme

#: Pylar's colour theme — matches the Laravel-style labels.
_THEME = Theme({
    "info": "bold cyan",
    "success": "bold green",
    "warn": "bold yellow",
    "error": "bold red",
    "muted": "dim",
    "label": "bold white",
    "accent": "bold magenta",
})


@runtime_checkable
class OutputWriter(Protocol):
    """Minimal write surface — anything with a ``write`` method works."""

    def write(self, text: str) -> int: ...


class Output:
    """A Rich-powered console output service for pylar CLI commands.

    Provides leveled messages (info, success, warn, error), Laravel-style
    action lines, beautiful tables, interactive prompts, and key-value
    displays — all with automatic colour/no-colour detection.
    """

    def __init__(
        self,
        writer: OutputWriter | None = None,
        *,
        colour: bool | None = None,
    ) -> None:
        if writer is not None and not isinstance(writer, StringIO):
            self._console = Console(
                file=writer,  # type: ignore[arg-type]
                theme=_THEME,
                force_terminal=colour,
            )
        elif isinstance(writer, StringIO):
            # Buffered capture (tests): use a generous width so tables
            # don't truncate cell contents based on a phantom 80-col tty.
            self._console = Console(
                file=writer,
                theme=_THEME,
                force_terminal=colour if colour is not None else None,
                width=200,
            )
        else:
            self._console = Console(
                file=writer,
                theme=_THEME,
                force_terminal=colour if colour is not None else None,
            )

    @property
    def console(self) -> Console:
        """Access the underlying Rich Console for advanced usage."""
        return self._console

    # --------------------------------------------------------------- raw

    def write(self, text: str) -> None:
        """Write *text* verbatim, no newline appended."""
        self._console.print(text, end="", highlight=False)

    def line(self, text: str = "") -> None:
        """Write *text* followed by a newline."""
        self._console.print(text, highlight=False)

    def newline(self, count: int = 1) -> None:
        """Print empty lines."""
        for _ in range(count):
            self._console.print()

    # ------------------------------------------------------ leveled output

    def info(self, message: str) -> None:
        """Print an INFO label + message."""
        self._console.print(f"  [info]INFO[/info]  {message}")

    def success(self, message: str) -> None:
        """Print a green SUCCESS label + message."""
        self._console.print(f"  [success]DONE[/success]  {message}")

    def warn(self, message: str) -> None:
        """Print a yellow WARN label + message."""
        self._console.print(f"  [warn]WARN[/warn]  {message}")

    def error(self, message: str) -> None:
        """Print a red ERROR label + message."""
        self._console.print(f"  [error]ERROR[/error] {message}")

    # -------------------------------------------------- Laravel-style action

    def action(self, verb: str, detail: str, *, duration_ms: float | None = None) -> None:
        """Print a Laravel-style action line: ``VERB  detail ... (duration)``."""
        time_part = f" [muted]({duration_ms:.2f}ms)[/muted]" if duration_ms is not None else ""
        self._console.print(f"  [success]{verb:12s}[/success] {detail}{time_part}")

    # ----------------------------------------------------------- table

    def table(
        self,
        headers: Sequence[str],
        rows: Iterable[Sequence[str]],
        *,
        title: str | None = None,
    ) -> None:
        """Print a Rich table with borders and optional title."""
        tbl = Table(title=title, show_lines=False, pad_edge=True, expand=False)
        for h in headers:
            tbl.add_column(h, style="label")
        for row in rows:
            tbl.add_row(*[str(c) for c in row])
        self._console.print()
        self._console.print(tbl)

    # ------------------------------------------------------- key-value

    def definitions(self, items: Sequence[tuple[str, str]]) -> None:
        """Print key-value pairs aligned like Laravel's ``about`` command."""
        if not items:
            return
        max_key = max(len(k) for k, _ in items)
        for key, value in items:
            self._console.print(
                f"  [label]{key.ljust(max_key)}[/label]  [muted]...[/muted]  {value}"
            )

    # ----------------------------------------------------------- prompts

    def confirm(self, message: str, *, default: bool = False) -> bool:
        """Ask the user for yes/no confirmation.

        Returns *default* when stdin is not a TTY (CI, pipes).
        """
        if not self._console.is_terminal:
            return default
        try:
            return Confirm.ask(f"  {message}", default=default, console=self._console)
        except (EOFError, KeyboardInterrupt):
            self.newline()
            return default

    # ----------------------------------------------------------- panel

    def panel(self, content: str, *, title: str | None = None, style: str = "info") -> None:
        """Print a bordered panel with optional title."""
        self._console.print(Panel(content, title=title, border_style=style))

    # ----------------------------------------------------------- rule

    def rule(self, title: str = "") -> None:
        """Print a horizontal rule with optional centered title."""
        self._console.rule(title, style="muted")


class BufferedOutput(Output):
    """An :class:`Output` that captures everything into an in-memory buffer.

    Colour escapes are disabled by default so assertions can match
    plain strings::

        out = BufferedOutput()
        await my_command.handle(my_input)
        assert "Done." in out.getvalue()
    """

    def __init__(self, *, colour: bool = False) -> None:
        self._buffer = StringIO()
        super().__init__(self._buffer, colour=colour)

    def getvalue(self) -> str:
        return self._buffer.getvalue()

    def clear(self) -> None:
        self._buffer.seek(0)
        self._buffer.truncate()
