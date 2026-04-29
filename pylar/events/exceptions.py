"""Exceptions raised by the events layer."""

from __future__ import annotations


class EventError(Exception):
    """Base class for event-bus errors."""


class ListenerRegistrationError(EventError):
    """Raised when a listener is registered for an incompatible event type."""
