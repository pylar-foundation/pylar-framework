"""Console commands for the foundation layer."""

from __future__ import annotations

from dataclasses import dataclass

from pylar.console.command import Command
from pylar.console.output import Output
from pylar.foundation.plugins import list_plugins


@dataclass(frozen=True)
class _PackageListInput:
    """No arguments — lists all installed pylar plugin packages."""


class PackageListCommand(Command[_PackageListInput]):
    """Display all installed packages that register ``pylar.providers`` entry points.

    Shows package name, version, entry point name, and the provider
    class reference.  This command does not load the provider classes —
    it reads metadata only, so it works even when a plugin has broken
    imports.
    """

    name = "package:list"
    description = "List installed pylar plugin packages"
    input_type = _PackageListInput

    def __init__(self, output: Output) -> None:
        self.out = output

    async def handle(self, input: _PackageListInput) -> int:
        plugins = list_plugins()

        if not plugins:
            self.out.info("No plugin packages found.")
            self.out.newline()
            self.out.line(
                "Third-party packages register providers via entry points:"
            )
            self.out.newline()
            self.out.line('  [project.entry-points."pylar.providers"]')
            self.out.line('  my_plugin = "my_package.provider:MyServiceProvider"')
            return 0

        rows: list[tuple[str, ...]] = []
        for p in plugins:
            rows.append((
                p.package or "(unknown)",
                p.version or "-",
                p.name,
                p.module,
            ))

        self.out.table(
            headers=("Package", "Version", "Name", "Provider"),
            rows=rows,
            title="Installed Packages",
        )
        self.out.newline()
        self.out.info(f"{len(plugins)} plugin(s) installed")
        return 0
