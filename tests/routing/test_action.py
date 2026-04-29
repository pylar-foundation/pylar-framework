"""Behavioural tests for :mod:`pylar.routing.action`."""

from __future__ import annotations

import pytest

from pylar.http import Request, Response, json
from pylar.routing import (
    Action,
    ControllerAction,
    FunctionAction,
    InvalidHandlerError,
)


# A standalone async function — should become a FunctionAction.
async def standalone_handler(request: Request) -> Response:
    return json({"kind": "function"})


def sync_handler(request: Request) -> Response:
    """A non-async handler — must be rejected."""
    return json({"kind": "sync"})


class SampleController:
    async def index(self, request: Request) -> Response:
        return json({"kind": "controller"})


class _NestedOuter:
    class Inner:
        async def show(self, request: Request) -> Response:  # pragma: no cover - never invoked
            return json({})


def test_standalone_function_becomes_function_action() -> None:
    action = Action.from_handler(standalone_handler)
    assert isinstance(action, FunctionAction)
    assert action.func is standalone_handler


def test_controller_method_becomes_controller_action() -> None:
    action = Action.from_handler(SampleController.index)
    assert isinstance(action, ControllerAction)
    assert action.controller_cls is SampleController
    assert action.method_name == "index"


def test_sync_handler_is_rejected() -> None:
    with pytest.raises(InvalidHandlerError, match="async def"):
        Action.from_handler(sync_handler)  # type: ignore[arg-type]


def test_non_callable_is_rejected() -> None:
    with pytest.raises(InvalidHandlerError, match="not callable"):
        Action.from_handler("not a callable")  # type: ignore[arg-type]


def test_nested_class_method_falls_back_to_function_action() -> None:
    # Nested classes are not safely identifiable via __qualname__ alone, so the
    # detector treats them as plain functions. The action will then fail at
    # call time (no `self` injection), which is intentional — pylar requires
    # top-level controller classes.
    action = Action.from_handler(_NestedOuter.Inner.show)
    assert isinstance(action, FunctionAction)
