"""Exceptions raised by the scheduling layer."""

from __future__ import annotations


class SchedulingError(Exception):
    """Base class for scheduling errors."""


class InvalidCronExpressionError(SchedulingError):
    """Raised when the cron expression supplied to a builder is malformed."""
