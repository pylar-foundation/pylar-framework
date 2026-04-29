"""Base class for typed job payloads."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class JobPayload(BaseModel):
    """Strict, frozen pydantic base for the data a job carries across the queue.

    Subclasses define the typed fields a job needs at execution time. Pylar
    serialises an instance to JSON when pushing onto the queue and validates
    it back into the typed payload before calling :meth:`Job.handle`, which
    means the worker side benefits from the same field-level guarantees the
    dispatcher side relied on.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        validate_assignment=True,
    )
