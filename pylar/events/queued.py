"""Generic queue job that re-runs a queued :class:`Listener`.

When a listener sets ``should_queue = True`` the bus does not invoke
its ``handle`` method directly. Instead it builds a
:class:`DispatchListenerPayload` carrying the fully qualified listener
and event class names plus the JSON-encoded event body, dispatches a
:class:`DispatchListenerJob`, and returns. A worker process pops the
record, resolves both classes, revives the event through pydantic, and
finally instantiates the listener via the container so any dependencies
that need re-resolving in the worker scope are wired correctly.

The pattern matches what :mod:`pylar.mail.jobs` does for queued
mailables — same shape, same trade-offs. Listeners that opt in must
make their event JSON-serialisable; the recommended layout is a
``pydantic.BaseModel``-based ``Event`` subclass.
"""

from __future__ import annotations

import importlib
from typing import Any, ClassVar

from pydantic import BaseModel

from pylar.events.event import Event
from pylar.events.exceptions import ListenerRegistrationError
from pylar.events.listener import Listener
from pylar.foundation.container import Container
from pylar.queue.job import Job
from pylar.queue.payload import JobPayload


class DispatchListenerPayload(JobPayload):
    """Wire format for a queued listener invocation."""

    listener_class: str
    event_class: str
    event_json: str


class DispatchListenerJob(Job[DispatchListenerPayload]):
    """Generic worker entry point for queued listeners."""

    payload_type: ClassVar[type[JobPayload]] = DispatchListenerPayload

    def __init__(self, container: Container) -> None:
        self._container = container

    async def handle(self, payload: DispatchListenerPayload) -> None:
        listener_cls = self._resolve(payload.listener_class, Listener)  # type: ignore[type-abstract]
        event_cls = self._resolve(payload.event_class, Event)
        if not issubclass(event_cls, BaseModel):
            raise ListenerRegistrationError(
                f"Queued listener {payload.listener_class!r} dispatched "
                f"event {payload.event_class!r} which is not a pydantic "
                "BaseModel and cannot be revived from JSON."
            )
        event = event_cls.model_validate_json(payload.event_json)
        listener = self._container.make(listener_cls)
        await listener.handle(event)

    @staticmethod
    def _resolve[T](qualified_name: str, base: type[T]) -> type[T]:
        module_name, _, class_name = qualified_name.rpartition(".")
        if not module_name or not class_name:
            raise ListenerRegistrationError(
                f"{qualified_name!r} is not a fully qualified name"
            )
        module = importlib.import_module(module_name)
        obj: Any = getattr(module, class_name, None)
        if not isinstance(obj, type) or not issubclass(obj, base):
            raise ListenerRegistrationError(
                f"{qualified_name} resolved to {obj!r}, "
                f"not a {base.__qualname__} subclass"
            )
        return obj
