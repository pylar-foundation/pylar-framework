"""Service provider that binds the application :class:`EventBus`.

Pylar's :class:`EventBus` is application-scoped — every dispatch goes
through the same instance, and listeners are registered eagerly during
the provider's :meth:`register` phase. The base provider here only sets
up the binding; user projects subclass it to declare their own listeners
in a single place::

    class AppEventServiceProvider(EventServiceProvider):
        def register_events(self, bus: EventBus) -> None:
            bus.listen(UserRegistered, SendWelcomeEmail)
            bus.listen(OrderShipped, NotifyCustomer)
            bus.listen(OrderShipped, UpdateInventory)

This keeps event wiring discoverable in one file instead of being
sprinkled across feature modules.
"""

from __future__ import annotations

from pylar.events.bus import EventBus
from pylar.foundation.container import Container
from pylar.foundation.provider import ServiceProvider


class EventServiceProvider(ServiceProvider):
    """Bind a singleton :class:`EventBus` and register the user's listeners."""

    def register(self, container: Container) -> None:
        bus = EventBus(container)
        self.register_events(bus)
        container.singleton(EventBus, lambda: bus)

    def register_events(self, bus: EventBus) -> None:
        """Override in user code to attach listeners.

        The default implementation is a no-op so projects with no events
        can list this provider in ``config/app.py`` without subclassing.
        """
