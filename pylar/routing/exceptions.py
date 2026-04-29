"""Exceptions raised by the routing layer."""

from __future__ import annotations


class RoutingError(Exception):
    """Base class for routing errors."""


class InvalidHandlerError(RoutingError):
    """Raised when a handler cannot be classified as a function or controller method."""


class RouteCompileError(RoutingError):
    """Raised when a pylar route cannot be translated into a Starlette route."""
