"""Exceptions raised by the database layer."""

from __future__ import annotations


class DatabaseError(Exception):
    """Base class for database errors raised by pylar."""


class NoActiveSessionError(DatabaseError):
    """Raised when a query is executed outside an active database session scope."""


class RecordNotFoundError(DatabaseError):
    """Raised by :meth:`QuerySet.get` when no row matches the primary key."""

    def __init__(self, model: type[object], primary_key: object) -> None:
        self.model = model
        self.primary_key = primary_key
        super().__init__(
            f"{model.__name__} with primary key {primary_key!r} was not found"
        )
