"""Code generators behind ``pylar make:*``."""

from pylar.console.make.commands import (
    ALL_MAKE_COMMANDS,
    SPECS,
    MakeCommand,
    MakeCommandCommand,
    MakeControllerCommand,
    MakeDtoCommand,
    MakeEventCommand,
    MakeFactoryCommand,
    MakeJobCommand,
    MakeListenerCommand,
    MakeMailableCommand,
    MakeModelCommand,
    MakeNameInput,
    MakeNotificationCommand,
    MakeObserverCommand,
    MakePolicyCommand,
    MakeProviderCommand,
)
from pylar.console.make.exceptions import (
    InvalidNameError,
    MakeError,
    TargetExistsError,
)
from pylar.console.make.generator import Generator, GeneratorSpec
from pylar.console.make.naming import to_kebab, to_snake, validate_pascal
from pylar.console.make.provider import MakeServiceProvider

__all__ = [
    "ALL_MAKE_COMMANDS",
    "SPECS",
    "Generator",
    "GeneratorSpec",
    "InvalidNameError",
    "MakeCommand",
    "MakeCommandCommand",
    "MakeControllerCommand",
    "MakeDtoCommand",
    "MakeError",
    "MakeEventCommand",
    "MakeFactoryCommand",
    "MakeJobCommand",
    "MakeListenerCommand",
    "MakeMailableCommand",
    "MakeModelCommand",
    "MakeNameInput",
    "MakeNotificationCommand",
    "MakeObserverCommand",
    "MakePolicyCommand",
    "MakeProviderCommand",
    "MakeServiceProvider",
    "TargetExistsError",
    "to_kebab",
    "to_snake",
    "validate_pascal",
]
