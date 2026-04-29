"""Group multiple listeners into a single subscriber class.

A :class:`Subscriber` is a small organisational helper: it lets a team
declare every listener for one bounded context (user lifecycle, order
state, audit log) inside a single class instead of dotting them across
the project. The bus calls :meth:`Subscriber.subscribe` once during the
service provider's ``register`` phase, and the subscriber attaches its
listeners to the bus.

Subscribers are *not* listeners themselves — they are containers of
listener registrations. Each method that should fire on an event is
still a :class:`Listener` subclass declared inside the same module (or
imported from anywhere); :meth:`subscribe` only wires them up.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pylar.events.bus import EventBus


class Subscriber(ABC):
    """Group of listener registrations bound to one :class:`EventBus`.

    Subclasses implement :meth:`subscribe` to attach their listeners
    to the supplied bus. The provider then calls
    ``MySubscriber().subscribe(bus)`` once during boot. Subscribers
    are stateless — pylar does not keep them around after the wiring
    call returns.

    Example::

        class UserSubscriber(Subscriber):
            def subscribe(self, bus: EventBus) -> None:
                bus.listen(UserRegistered, SendWelcomeListener)
                bus.listen(UserDeleted, CleanupAssetsListener)
    """

    @abstractmethod
    def subscribe(self, bus: EventBus) -> None:
        """Attach this subscriber's listeners to *bus*."""
