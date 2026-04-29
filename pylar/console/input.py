"""Translate a frozen dataclass into an :mod:`argparse` parser and back.

This module is the only place in pylar that knows about ``argparse``. The
``Command`` base class delegates to it so that subclasses describe their
input as a plain dataclass and never touch parsers themselves.

Mapping rules
-------------

For every field on the input dataclass:

* ``bool`` field with a default of ``False`` becomes ``--name`` (store_true).
* ``bool`` field with a default of ``True`` becomes ``--no-name`` (store_false).
* Field annotated as ``X | None`` (or ``Optional[X]``) becomes ``--name X``
  with a default of ``None``.
* Field with any other type and a default value becomes ``--name X`` with
  that default.
* Field with no default becomes a positional argument and is required.

Field names are converted from ``snake_case`` to ``--kebab-case`` for the CLI
flag, but argparse stores them under the original underscore name in its
namespace, so reconstruction by ``getattr(ns, field.name)`` is unambiguous.
"""

from __future__ import annotations

import argparse
from dataclasses import MISSING, Field, fields, is_dataclass
from types import NoneType, UnionType
from typing import Any, Union, get_args, get_origin, get_type_hints

from pylar.console.exceptions import ArgumentParseError, CommandDefinitionError


def build_parser(input_cls: type[Any], *, prog: str, description: str) -> argparse.ArgumentParser:
    """Construct an :class:`argparse.ArgumentParser` for *input_cls*."""
    if not is_dataclass(input_cls):
        raise CommandDefinitionError(
            f"{input_cls.__qualname__} must be a dataclass to be used as a command input"
        )

    parser = _SilentArgumentParser(prog=prog, description=description, add_help=True)
    hints = get_type_hints(input_cls)

    for field in fields(input_cls):
        annotation = hints.get(field.name, field.type)
        _add_field(parser, field, annotation)

    return parser


def parse_args(input_cls: type[Any], parser: argparse.ArgumentParser, argv: list[str]) -> Any:
    """Run *parser* over *argv* and return an instance of *input_cls*."""
    try:
        namespace = parser.parse_args(argv)
    except _ArgparseExitError as exc:
        raise ArgumentParseError(exc.message) from None

    field_values: dict[str, object] = {}
    for field in fields(input_cls):
        field_values[field.name] = getattr(namespace, field.name)
    return input_cls(**field_values)


# ----------------------------------------------------------------------- helpers


def _add_field(parser: argparse.ArgumentParser, field: Field[Any], annotation: Any) -> None:
    underlying, is_optional = _decompose_optional(annotation)
    has_default = field.default is not MISSING
    default = field.default if has_default else None
    flag = "--" + field.name.replace("_", "-")
    help_text = _help_for(field)

    if underlying is bool:
        if not has_default:
            raise CommandDefinitionError(
                f"Boolean field {field.name!r} must declare a default value"
            )
        if default is False:
            parser.add_argument(
                flag, dest=field.name, action="store_true", default=False, help=help_text
            )
        else:
            negative_flag = "--no-" + field.name.replace("_", "-")
            parser.add_argument(
                negative_flag,
                dest=field.name,
                action="store_false",
                default=True,
                help=help_text,
            )
        return

    if is_optional or has_default:
        parser.add_argument(
            flag,
            dest=field.name,
            type=underlying,
            default=default,
            help=help_text,
        )
        return

    # Positional, required.
    parser.add_argument(field.name, type=underlying, help=help_text)


def _decompose_optional(annotation: Any) -> tuple[Any, bool]:
    """Return ``(underlying_type, is_optional)`` for ``X``, ``X | None``, ``Optional[X]``."""
    origin = get_origin(annotation)
    if origin is Union or origin is UnionType:
        args = [a for a in get_args(annotation) if a is not NoneType]
        if len(args) == 1:
            return args[0], True
        raise CommandDefinitionError(
            f"Unsupported union type {annotation!r}: pylar commands accept only `T | None`"
        )
    return annotation, False


def _help_for(field: Field[Any]) -> str | None:
    metadata: dict[str, Any] = dict(field.metadata or {})
    raw = metadata.get("help")
    return str(raw) if raw is not None else None


# ----------------------------- argparse without sys.exit -------------------------


class _ArgparseExitError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class _SilentArgumentParser(argparse.ArgumentParser):
    """Argparse subclass that raises instead of calling :func:`sys.exit`.

    Argparse normally writes errors to stderr and terminates the process,
    which is fine for a top-level CLI but breaks the framework's contract:
    a misbehaving command should bubble up an exception so the kernel can
    decide how to render it.
    """

    def error(self, message: str) -> Any:
        raise _ArgparseExitError(message)
