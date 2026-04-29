"""Exceptions raised by the mail layer."""

from __future__ import annotations


class MailError(Exception):
    """Base class for mail-layer errors."""


class MailableDefinitionError(MailError):
    """Raised when a Mailable subclass returns a malformed Message."""


class TransportError(MailError):
    """Raised when the bound transport fails to deliver a message."""
