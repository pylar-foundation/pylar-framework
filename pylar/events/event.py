"""Marker base class for application events.

An :class:`Event` is a small immutable record describing something that
happened in the domain — ``UserRegistered``, ``OrderShipped``,
``InvoicePaid``. Subclasses are typically frozen dataclasses with strongly
typed fields. The class is intentionally empty: pylar's event bus dispatches
on the concrete subclass type, not on any methods or attributes the parent
might define.

Pylar separates these high-level domain events from the low-level model
lifecycle hooks shipped in :mod:`pylar.database.observer`. Observers fire
around persistence calls and live next to the model they protect; events
are dispatched explicitly from controllers, services, and jobs whenever
the application has something interesting to announce.
"""

from __future__ import annotations


class Event:
    """Base class for every dispatched event. Subclass with a frozen dataclass."""
