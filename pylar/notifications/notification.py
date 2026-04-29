"""Base class for notifications dispatched to one or more channels."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, ClassVar, Self

from pylar.queue.payload import JobPayload

if TYPE_CHECKING:
    from pylar.foundation.container import Container
    from pylar.notifications.contracts import Notifiable


class Notification(ABC):
    """A piece of information to be delivered through one or more channels.

    Subclasses describe the content (typed fields on ``__init__``) and
    declare *which* channels will deliver them via the :meth:`via` hook.
    Each channel looks at the notification for an extra method that
    knows how to render itself for that channel: ``to_mail`` for the
    mail channel, ``to_array`` for the database channel, and so on.
    Pylar does not enforce these methods at the base class so that
    notifications only carry the renderers they actually need.

    Queueable notifications opt in by setting ``should_queue = True``
    and implementing :meth:`to_payload` / :meth:`from_payload`. The
    dispatcher then hands the work off to a generic
    ``DeliverNotificationJob`` instead of running channels inline.
    """

    #: Opt the notification into queue dispatch. The dispatcher
    #: serialises the notification *and* the notifiable through the
    #: hooks below, pushes a generic ``DeliverNotificationJob``, and
    #: returns. A worker process re-runs the channel chain inside its
    #: own scope.
    should_queue: ClassVar[bool] = False

    #: Optional payload type for queue serialisation. Required only
    #: when ``should_queue = True``.
    payload_type: ClassVar[type[JobPayload] | None] = None

    @abstractmethod
    def via(self) -> tuple[str, ...]:
        """Return the channel keys this notification will be delivered through."""

    def to_payload(self, notifiable: Notifiable) -> JobPayload:
        """Serialise the notification *and* its target into a JobPayload.

        The payload must carry enough information to rebuild both
        sides on the worker — typically a model id pair plus whatever
        notification fields the renderer needs.
        """
        raise NotImplementedError(
            f"{type(self).__qualname__} does not support queuing — "
            "override to_payload/from_payload to opt in."
        )

    @classmethod
    def from_payload(
        cls,
        container: Container,
        payload: JobPayload,
    ) -> tuple[Notifiable, Self]:
        """Rebuild ``(notifiable, notification)`` from a JobPayload.

        Implementations typically re-fetch the notifiable through the
        ORM (using the model id stored in the payload) and reconstruct
        the notification from the remaining fields.
        """
        raise NotImplementedError(
            f"{cls.__qualname__} does not support queuing — "
            "override to_payload/from_payload to opt in."
        )
