"""Exceptions raised by the notifications layer."""

from __future__ import annotations


class NotificationError(Exception):
    """Base class for notification errors."""


class UnknownChannelError(NotificationError):
    """Raised when a notification asks for a channel that is not registered."""

    def __init__(self, channel: str) -> None:
        self.channel = channel
        super().__init__(f"No notification channel registered under {channel!r}")


class ChannelDispatchError(NotificationError):
    """Raised when a channel cannot deliver a notification."""
