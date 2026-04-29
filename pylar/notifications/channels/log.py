"""Notification channel that writes to a logger."""

from __future__ import annotations

import logging

from pylar.notifications.contracts import Notifiable
from pylar.notifications.notification import Notification


class LogChannel:
    """A development / fallback channel that records notifications via logging.

    Notifications opt in by exposing a ``to_log(notifiable) -> str`` hook.
    Useful as a sanity check during development and as a fallback channel
    when the real delivery mechanism is misconfigured.
    """

    name = "log"

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger("pylar.notifications")

    async def send(self, notifiable: Notifiable, notification: Notification) -> None:
        renderer = getattr(notification, "to_log", None)
        body: str
        if callable(renderer):
            body = str(renderer(notifiable))
        else:
            body = type(notification).__qualname__
        self._logger.info(
            "NOTIFY channel=log target=%s body=%s",
            notifiable.routes_for("log") or "<unrouted>",
            body,
        )
