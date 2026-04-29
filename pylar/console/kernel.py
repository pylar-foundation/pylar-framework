"""The console kernel — drives an :class:`Application` from ``argv``."""

from __future__ import annotations

import sys
from typing import Any

from pylar.console.builtin import HelpCommand, ListCommand
from pylar.console.command import Command
from pylar.console.exceptions import (
    ArgumentParseError,
    CommandDefinitionError,
    CommandNotFoundError,
)
from pylar.console.output import Output
from pylar.foundation.application import Application

#: Container tag under which user code registers its commands.
COMMANDS_TAG = "console.commands"


class ConsoleKernel:
    """Implements :class:`pylar.foundation.Kernel` for command-line entry."""

    def __init__(self, app: Application, argv: list[str]) -> None:
        self.app = app
        self.argv = argv

    async def handle(self) -> int:
        await self.app.bootstrap()
        self._register_builtin_commands()
        # Bind a default Output unless the application already provides
        # one. Commands depending on Output through their __init__
        # receive the same singleton across the run.
        if not self.app.container.has(Output):
            self.app.container.singleton(Output, Output)

        if not self.argv:
            return await self._dispatch("list", [])

        command_name, rest = self.argv[0], self.argv[1:]
        try:
            return await self._dispatch(command_name, rest)
        except CommandNotFoundError as exc:
            sys.stderr.write(f"{exc}\n")
            return 1
        except ArgumentParseError as exc:
            sys.stderr.write(f"Argument error: {exc}\n")
            return 2
        except CommandDefinitionError as exc:
            sys.stderr.write(f"Command definition error: {exc}\n")
            return 3

    # ------------------------------------------------------------------ internals

    def _register_builtin_commands(self) -> None:
        # Lazy imports to avoid circular dependencies.
        from pylar.console.tinker import TinkerCommand
        from pylar.foundation.commands import PackageListCommand

        existing = self.app.container.tagged_types(COMMANDS_TAG)
        to_register: list[type[Command[Any]]] = []
        if ListCommand not in existing:
            to_register.append(ListCommand)
        if HelpCommand not in existing:
            to_register.append(HelpCommand)
        if TinkerCommand not in existing:
            to_register.append(TinkerCommand)
        if PackageListCommand not in existing:
            to_register.append(PackageListCommand)
        if to_register:
            self.app.container.tag(to_register, COMMANDS_TAG)

    def _command_index(self) -> dict[str, type[Command[Any]]]:
        index: dict[str, type[Command[Any]]] = {}
        for cls in self.app.container.tagged_types(COMMANDS_TAG):
            if not issubclass(cls, Command):
                raise CommandDefinitionError(
                    f"{cls.__qualname__} is tagged as a console command but does not "
                    f"subclass pylar.console.Command"
                )
            name = cls.name
            if not name:
                raise CommandDefinitionError(
                    f"{cls.__qualname__} is missing a `name` attribute"
                )
            if name in index:
                raise CommandDefinitionError(
                    f"Duplicate command name {name!r}: {cls.__qualname__} and "
                    f"{index[name].__qualname__}"
                )
            index[name] = cls
        return index

    async def _dispatch(self, name: str, argv: list[str]) -> int:
        index = self._command_index()
        if name not in index:
            raise CommandNotFoundError(
                f"Unknown command {name!r}. Run `pylar list` to see available commands."
            )

        command_cls = index[name]
        parsed_input = command_cls.parse(argv)
        command = self.app.container.make(command_cls)
        async with self._ambient_session_scope():
            return await command.handle(parsed_input)

    def _ambient_session_scope(self) -> Any:
        """Open an ambient DB session for the command if a manager is bound.

        Lets commands (seeders, custom user commands, scheduled tasks
        executed via ``schedule:run``, etc.) rely on
        :func:`pylar.database.current_session` without needing to wrap
        themselves in ``use_session`` — matching how the HTTP middleware
        and the queue worker already behave.
        """
        from contextlib import asynccontextmanager

        from pylar.database.connection import ConnectionManager
        from pylar.database.session import ambient_session

        if not self.app.container.has(ConnectionManager):
            @asynccontextmanager
            async def _noop() -> Any:
                yield

            return _noop()

        manager = self.app.container.make(ConnectionManager)
        return ambient_session(manager)
