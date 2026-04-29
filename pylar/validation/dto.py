"""Base classes for typed request input DTOs."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class RequestDTO(BaseModel):
    """Strict, frozen pydantic base for body / query DTOs.

    Defaults match the rest of pylar: unknown fields are rejected, instances
    are immutable after construction, and assignment to fields after the
    fact is validated. Subclasses are free to relax these via
    ``model_config`` if they have a good reason.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        validate_assignment=True,
        str_strip_whitespace=True,
    )


class HeaderDTO(BaseModel):
    """Strict pydantic base bound to ``request.headers``.

    Subclass and declare typed fields whose names map to header names::

        class WebhookHeaders(HeaderDTO):
            signature: str = Field(alias="x-signature")
            delivery_id: str = Field(alias="x-delivery-id")

    The router auto-resolver scans handler parameters for ``HeaderDTO``
    annotations the same way it scans for ``RequestDTO``. Header lookup
    is case-insensitive — pylar lower-cases keys before validation so
    ``X-Signature`` and ``x-signature`` resolve to the same field.

    Unknown headers are *ignored* (``extra="ignore"``) because real HTTP
    traffic carries plenty of proxy / cache / accept-* headers the
    application has no business validating.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="ignore",
        populate_by_name=True,
        validate_assignment=True,
        str_strip_whitespace=True,
    )


class CookieDTO(BaseModel):
    """Strict pydantic base bound to ``request.cookies``.

    Used for opaque tokens that should not appear in URLs or bodies.
    Field names map directly to cookie names; use ``Field(alias=...)``
    when the cookie has a non-Python-identifier name. Unknown cookies
    are ignored, same reasoning as :class:`HeaderDTO`.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="ignore",
        populate_by_name=True,
        validate_assignment=True,
        str_strip_whitespace=True,
    )
