"""Exceptions raised by the queue layer."""

from __future__ import annotations


class QueueError(Exception):
    """Base class for queue errors."""


class JobResolutionError(QueueError):
    """Raised when a worker cannot import the job class named in a record."""


class JobDefinitionError(QueueError):
    """Raised when a Job subclass is missing ``payload_type`` or is otherwise malformed."""
