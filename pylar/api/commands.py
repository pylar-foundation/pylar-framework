"""``pylar api:docs`` — dump the OpenAPI spec to stdout or a file."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from pylar.api.openapi import generate_openapi
from pylar.api.provider import ApiDocsConfig
from pylar.console.command import Command
from pylar.console.output import Output
from pylar.routing import Router


@dataclass(frozen=True)
class _ApiDocsInput:
    output: str = field(
        default="",
        metadata={"help": "Write the spec to this file (default: stdout)"},
    )
    indent: int = field(
        default=2,
        metadata={"help": "JSON indent — 0 for single-line output"},
    )


class ApiDocsCommand(Command[_ApiDocsInput]):
    """Emit the OpenAPI 3.1 document for the current router.

    Useful for CI pipelines that feed the spec into contract tests,
    client-code generators, or hosted API-docs portals. Run without
    ``--output`` to print to stdout; pass a path to write the file.
    """

    name = "api:docs"
    description = "Dump the OpenAPI spec to stdout or a file"
    input_type = _ApiDocsInput

    def __init__(
        self,
        router: Router,
        config: ApiDocsConfig,
        output: Output,
    ) -> None:
        self.router = router
        self.config = config
        self.out = output

    async def handle(self, input: _ApiDocsInput) -> int:
        spec = generate_openapi(
            self.router,
            title=self.config.title,
            version=self.config.version,
            description=self.config.description,
            servers=self.config.servers,
        )
        rendered = json.dumps(spec, indent=input.indent or None, sort_keys=False)

        if input.output:
            target = Path(input.output)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(rendered + "\n", encoding="utf-8")
            self.out.success(f"Wrote {target}")
        else:
            self.out.line(rendered)
        return 0
