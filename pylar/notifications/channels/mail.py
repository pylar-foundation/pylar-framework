"""Notification channel that delivers via the mail layer."""

from __future__ import annotations

from pylar.mail.mailable import Mailable
from pylar.mail.mailer import Mailer
from pylar.notifications.contracts import Notifiable
from pylar.notifications.exceptions import ChannelDispatchError
from pylar.notifications.notification import Notification


class MailChannel:
    """Hand the notification to the bound :class:`Mailer`.

    Notifications opt in by implementing ``to_mail(notifiable) ->
    Mailable``. The channel calls that hook to obtain a typed mailable
    and forwards it to the mailer — every layer above the transport
    therefore stays unaware of the SMTP / SES / API specifics.
    """

    name = "mail"

    def __init__(self, mailer: Mailer) -> None:
        self._mailer = mailer

    async def send(self, notifiable: Notifiable, notification: Notification) -> None:
        renderer = getattr(notification, "to_mail", None)
        if not callable(renderer):
            raise ChannelDispatchError(
                f"{type(notification).__qualname__} has no to_mail() method — "
                f"cannot deliver via the mail channel"
            )
        mailable = renderer(notifiable)
        if not isinstance(mailable, Mailable):
            raise ChannelDispatchError(
                f"{type(notification).__qualname__}.to_mail() must return a Mailable, "
                f"got {type(mailable).__qualname__}"
            )
        await self._mailer.send(mailable)
