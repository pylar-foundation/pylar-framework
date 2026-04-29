"""Console commands behind every ``pylar make:*`` generator.

Each subclass declares only its ``name``, ``description``, and the
:class:`GeneratorSpec` it drives. The shared :meth:`MakeCommand.handle`
method instantiates a :class:`Generator`, writes the file, and reports
the result. The 13 subclasses below cover the full surface a project
needs to scaffold.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

from pylar.console.command import Command
from pylar.console.make.exceptions import (
    InvalidNameError,
    TargetExistsError,
)
from pylar.console.make.generator import Generator, GeneratorSpec
from pylar.console.output import Output
from pylar.foundation.application import Application


@dataclass(frozen=True)
class MakeNameInput:
    name: str = field(metadata={"help": "PascalCase class name to generate"})
    force: bool = field(
        default=False,
        metadata={"help": "Overwrite the target file if it already exists"},
    )


@dataclass(frozen=True)
class MakeModelInput(MakeNameInput):
    migration: bool = field(
        default=False,
        metadata={"help": "Also create a migration for this model"},
    )


@dataclass(frozen=True)
class MakeControllerInput(MakeNameInput):
    resource: bool = field(
        default=False,
        metadata={"help": "Generate a full REST resource (index/store/show/update/destroy)"},
    )


@dataclass(frozen=True)
class MakeTypedInput(MakeNameInput):
    """Input for generators that accept an extra class reference (--event, --model)."""

    event: str = field(
        default="",
        metadata={"help": "Concrete Event class to type the listener against"},
    )
    model: str = field(
        default="",
        metadata={"help": "Concrete Model class for the policy/factory"},
    )


# ----------------------------------------------------------------- specs


SPECS: dict[str, GeneratorSpec] = {
    "model": GeneratorSpec(
        template="model.py.template",
        target="app/models/${snake_name}.py",
        description="Create a new Model class",
    ),
    "controller": GeneratorSpec(
        template="controller.py.template",
        target="app/http/controllers/${snake_name}.py",
        description="Create a new HTTP controller",
    ),
    "provider": GeneratorSpec(
        template="provider.py.template",
        target="app/providers/${snake_name}.py",
        description="Create a new ServiceProvider",
    ),
    "command": GeneratorSpec(
        template="command.py.template",
        target="app/console/commands/${snake_name}.py",
        description="Create a new console Command",
    ),
    "dto": GeneratorSpec(
        template="dto.py.template",
        target="app/http/requests/${snake_name}.py",
        description="Create a new RequestDTO",
    ),
    "job": GeneratorSpec(
        template="job.py.template",
        target="app/jobs/${snake_name}.py",
        description="Create a new queueable Job",
    ),
    "event": GeneratorSpec(
        template="event.py.template",
        target="app/events/${snake_name}.py",
        description="Create a new Event",
    ),
    "listener": GeneratorSpec(
        template="listener.py.template",
        target="app/listeners/${snake_name}.py",
        description="Create a new event Listener",
    ),
    "policy": GeneratorSpec(
        template="policy.py.template",
        target="app/policies/${snake_name}.py",
        description="Create a new Policy",
    ),
    "mailable": GeneratorSpec(
        template="mailable.py.template",
        target="app/mail/${snake_name}.py",
        description="Create a new Mailable",
    ),
    "notification": GeneratorSpec(
        template="notification.py.template",
        target="app/notifications/${snake_name}.py",
        description="Create a new Notification",
    ),
    "factory": GeneratorSpec(
        template="factory.py.template",
        target="database/factories/${snake_name}.py",
        description="Create a new test Factory",
    ),
    "observer": GeneratorSpec(
        template="observer.py.template",
        target="app/observers/${snake_name}.py",
        description="Create a new model Observer",
    ),
    "middleware": GeneratorSpec(
        template="middleware.py.template",
        target="app/http/middleware/${snake_name}.py",
        description="Create a new HTTP middleware",
    ),
    "test": GeneratorSpec(
        template="test.py.template",
        target="tests/test_${snake_name}.py",
        description="Create a new test class",
    ),
    "seeder": GeneratorSpec(
        template="seeder.py.template",
        target="database/seeds/${snake_name}.py",
        description="Create a new database seeder",
    ),
    "controller_resource": GeneratorSpec(
        template="controller_resource.py.template",
        target="app/http/controllers/${snake_name}.py",
        description="Create a full REST resource controller",
    ),
    "listener_typed": GeneratorSpec(
        template="listener_typed.py.template",
        target="app/listeners/${snake_name}.py",
        description="Create a typed event Listener",
    ),
    "policy_typed": GeneratorSpec(
        template="policy_typed.py.template",
        target="app/policies/${snake_name}.py",
        description="Create a typed Policy",
    ),
    "factory_typed": GeneratorSpec(
        template="factory_typed.py.template",
        target="database/factories/${snake_name}.py",
        description="Create a typed test Factory",
    ),
}


# ----------------------------------------------------------------- base


def _run_generator(
    spec: GeneratorSpec,
    base_path: Path,
    name: str,
    output: Output,
    *,
    force: bool = False,
    extra_class: str = "",
) -> int | None:
    """Run a :class:`Generator` and print the result.

    Returns ``None`` on success (so callers can ``return ... or 0``),
    or a non-zero exit code on failure.
    """
    try:
        generator = Generator(
            spec, base_path, name, force=force, extra_class=extra_class,
        )
        target = generator.write()
    except InvalidNameError as exc:
        output.error(str(exc))
        return 2
    except TargetExistsError as exc:
        output.error(str(exc))
        return 1
    try:
        relative = target.relative_to(base_path)
    except ValueError:
        relative = target
    output.action("Created", str(relative))
    return None


class MakeCommand(Command[MakeNameInput]):
    """Shared implementation for every ``make:*`` console command."""

    spec: ClassVar[GeneratorSpec]
    input_type = MakeNameInput

    def __init__(self, application: Application, output: Output) -> None:
        self._application = application
        self.out = output

    async def handle(self, input: MakeNameInput) -> int:
        return _run_generator(
            self.spec, self._application.base_path, input.name, self.out,
            force=input.force,
        ) or 0


# ----------------------------------------------------------------- subclasses


class MakeModelCommand(MakeCommand):
    name = "make:model"
    description = SPECS["model"].description
    spec = SPECS["model"]

    async def handle(self, input: MakeNameInput) -> int:
        result = _run_generator(
            self.spec, self._application.base_path, input.name, self.out,
            force=input.force,
        )
        if result is not None:
            return result
        if getattr(input, "migration", False):
            from pylar.console.make.naming import to_snake

            snake = to_snake(input.name)
            self.out.info(
                f"Run `pylar make:migration create_{snake}s` to create the migration."
            )
        return 0


class MakeControllerCommand(MakeCommand):
    name = "make:controller"
    description = SPECS["controller"].description
    spec = SPECS["controller"]

    async def handle(self, input: MakeNameInput) -> int:
        if getattr(input, "resource", False):
            return _run_generator(
                SPECS["controller_resource"], self._application.base_path,
                input.name, self.out, force=input.force,
            ) or 0
        return _run_generator(
            self.spec, self._application.base_path, input.name, self.out, force=input.force,
        ) or 0


class MakeProviderCommand(MakeCommand):
    name = "make:provider"
    description = SPECS["provider"].description
    spec = SPECS["provider"]


class MakeCommandCommand(MakeCommand):
    name = "make:command"
    description = SPECS["command"].description
    spec = SPECS["command"]


class MakeDtoCommand(MakeCommand):
    name = "make:dto"
    description = SPECS["dto"].description
    spec = SPECS["dto"]


class MakeJobCommand(MakeCommand):
    name = "make:job"
    description = SPECS["job"].description
    spec = SPECS["job"]


class MakeEventCommand(MakeCommand):
    name = "make:event"
    description = SPECS["event"].description
    spec = SPECS["event"]


class MakeListenerCommand(MakeCommand):
    name = "make:listener"
    description = SPECS["listener"].description
    spec = SPECS["listener"]

    async def handle(self, input: MakeNameInput) -> int:
        event = getattr(input, "event", "")
        if event:
            return _run_generator(
                SPECS["listener_typed"], self._application.base_path, input.name, self.out,
                force=input.force, extra_class=event,
            ) or 0
        return _run_generator(
            self.spec, self._application.base_path, input.name, self.out, force=input.force,
        ) or 0


class MakePolicyCommand(MakeCommand):
    name = "make:policy"
    description = SPECS["policy"].description
    spec = SPECS["policy"]

    async def handle(self, input: MakeNameInput) -> int:
        model = getattr(input, "model", "")
        if model:
            return _run_generator(
                SPECS["policy_typed"], self._application.base_path, input.name, self.out,
                force=input.force, extra_class=model,
            ) or 0
        return _run_generator(
            self.spec, self._application.base_path, input.name, self.out, force=input.force,
        ) or 0


class MakeMailableCommand(MakeCommand):
    name = "make:mailable"
    description = SPECS["mailable"].description
    spec = SPECS["mailable"]


class MakeNotificationCommand(MakeCommand):
    name = "make:notification"
    description = SPECS["notification"].description
    spec = SPECS["notification"]


class MakeFactoryCommand(MakeCommand):
    name = "make:factory"
    description = SPECS["factory"].description
    spec = SPECS["factory"]

    async def handle(self, input: MakeNameInput) -> int:
        model = getattr(input, "model", "")
        if model:
            return _run_generator(
                SPECS["factory_typed"], self._application.base_path, input.name, self.out,
                force=input.force, extra_class=model,
            ) or 0
        return _run_generator(
            self.spec, self._application.base_path, input.name, self.out, force=input.force,
        ) or 0


class MakeObserverCommand(MakeCommand):
    name = "make:observer"
    description = SPECS["observer"].description
    spec = SPECS["observer"]


class MakeMiddlewareCommand(MakeCommand):
    name = "make:middleware"
    description = SPECS["middleware"].description
    spec = SPECS["middleware"]


class MakeTestCommand(MakeCommand):
    name = "make:test"
    description = SPECS["test"].description
    spec = SPECS["test"]


class MakeSeederCommand(MakeCommand):
    name = "make:seeder"
    description = SPECS["seeder"].description
    spec = SPECS["seeder"]


ALL_MAKE_COMMANDS: tuple[type[MakeCommand], ...] = (
    MakeModelCommand,
    MakeControllerCommand,
    MakeProviderCommand,
    MakeCommandCommand,
    MakeDtoCommand,
    MakeJobCommand,
    MakeEventCommand,
    MakeListenerCommand,
    MakePolicyCommand,
    MakeMailableCommand,
    MakeNotificationCommand,
    MakeFactoryCommand,
    MakeObserverCommand,
    MakeMiddlewareCommand,
    MakeTestCommand,
    MakeSeederCommand,
)
