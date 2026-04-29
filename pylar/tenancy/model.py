"""The :class:`Tenant` base model — subclass in app code to add billing etc."""

from __future__ import annotations

from pylar.database import Model, TimestampsMixin, fields


class Tenant(Model, TimestampsMixin):  # type: ignore[metaclass]
    """Minimal tenant row — apps subclass and add plan / billing fields.

    ``slug`` and ``domain`` are the two identifiers the bundled
    resolvers look up; ``schema_name`` and ``database_url`` are
    reserved for the tier-B and tier-C isolation strategies defined
    in ADR-0011 (shipped in a follow-up).
    """

    class Meta:
        db_table = "tenants"

    slug = fields.SlugField(max_length=64, unique=True, index=True)
    name = fields.CharField(max_length=200)
    domain = fields.CharField(max_length=255, unique=True, null=True, index=True)
    schema_name = fields.CharField(max_length=64, null=True)
    database_url = fields.CharField(max_length=512, null=True)
    is_active = fields.BooleanField(default=True)
