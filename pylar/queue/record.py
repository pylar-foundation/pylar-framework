"""The wire format that crosses the queue boundary."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field


def _utc_now() -> datetime:
    return datetime.now(UTC)


class JobRecord(BaseModel):
    """A serialised job ready to be stored, transmitted, or popped.

    The record carries enough metadata for any worker process — possibly
    running on a different machine — to import the right :class:`Job` class
    and rebuild the typed payload from JSON. ``job_class`` is the fully
    qualified name (``module.ClassName``); ``payload_json`` is the
    pydantic ``model_dump_json`` output of the typed payload instance.

    ``available_at`` is the earliest moment a worker is allowed to pop
    the record. The dispatcher sets it to ``queued_at`` for an immediate
    job and to ``queued_at + delay`` for a delayed one; drivers respect
    the field on pop.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    job_class: str
    payload_json: str
    queue: str = "default"
    attempts: int = 0
    queued_at: datetime = Field(default_factory=_utc_now)
    available_at: datetime = Field(default_factory=_utc_now)
