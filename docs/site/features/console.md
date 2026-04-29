# Console

Pylar's console layer provides a typed command system driven by frozen dataclasses. Commands declare their input as a dataclass, receive services through constructor injection, and are dispatched by the `ConsoleKernel`.

## Writing a command

Define a frozen dataclass for the input and subclass `Command[InputT]`:

```python
from dataclasses import dataclass, field
from pylar.console import Command


@dataclass(frozen=True)
class GreetInput:
    name: str = field(metadata={"help": "Who to greet"})
    shout: bool = False


class GreetCommand(Command[GreetInput]):
    name = "greet"
    description = "Greet someone by name"
    input_type = GreetInput

    def __init__(self, logger: Logger) -> None:
        self.logger = logger

    async def handle(self, input: GreetInput) -> int:
        message = f"Hello, {input.name}!"
        if input.shout:
            message = message.upper()
        self.logger.info(message)
        return 0
```

The dataclass-to-argparse mapping follows these rules:

- Fields without a default become positional arguments.
- `bool` fields with `default=False` become `--flag` (store_true).
- `bool` fields with `default=True` become `--no-flag` (store_false).
- `X | None` fields become optional `--name` flags.
- Names are converted from `snake_case` to `--kebab-case` on the CLI.

## Registering commands

Tag command classes in your service provider:

```python
from pylar.console import COMMANDS_TAG

class AppServiceProvider(ServiceProvider):
    def register(self) -> None:
        self.app.container.tag([GreetCommand], COMMANDS_TAG)
```

The `ConsoleKernel` discovers all classes tagged with `COMMANDS_TAG` and builds an index keyed by the `name` class attribute.

## The pylar entrypoint

The `pylar` CLI script is the standard entry point. It loads `config/app.py` from the current directory, constructs an `Application`, and hands `sys.argv` to the `ConsoleKernel`:

```bash
$ pylar greet Alice --shout
HELLO, ALICE!

$ pylar list           # show all registered commands
$ pylar help greet     # show help for a specific command
```

## ConsoleKernel

The kernel bootstraps the application, registers built-in commands (`list`, `help`), and dispatches to the matching command class:

```python
from pylar.console import ConsoleKernel
from pylar.foundation import Application

kernel = ConsoleKernel(app=app, argv=["greet", "Alice"])
exit_code = await kernel.handle()
```

Exit codes: `0` success, `1` command not found, `2` argument parse error, `3` command definition error.

## Code generators (make:*)

Pylar ships 13 `make:*` generators that scaffold common classes. Each accepts a PascalCase name and an optional `--force` flag to overwrite existing files:

| Command | Creates |
|---|---|
| `make:model` | `app/models/<name>.py` |
| `make:controller` | `app/http/controllers/<name>.py` |
| `make:provider` | `app/providers/<name>.py` |
| `make:command` | `app/console/commands/<name>.py` |
| `make:dto` | `app/http/requests/<name>.py` |
| `make:job` | `app/jobs/<name>.py` |
| `make:event` | `app/events/<name>.py` |
| `make:listener` | `app/listeners/<name>.py` |
| `make:policy` | `app/policies/<name>.py` |
| `make:mailable` | `app/mail/<name>.py` |
| `make:notification` | `app/notifications/<name>.py` |
| `make:factory` | `database/factories/<name>.py` |
| `make:observer` | `app/observers/<name>.py` |

Example:

```bash
$ pylar make:model BlogPost
Created app/models/blog_post.py

$ pylar make:controller BlogPost --force
Created app/http/controllers/blog_post.py
```

All generators share a single `MakeCommand` base class that instantiates a `Generator` with a `GeneratorSpec`, writes the file from a template, and reports the result. The `--force` flag overwrites the target if it already exists.

## Creating a new project

```bash
$ pylar new myapp
```

This runs outside any existing project and scaffolds a fresh directory structure with `config/app.py`, default providers, and the standard layout.
