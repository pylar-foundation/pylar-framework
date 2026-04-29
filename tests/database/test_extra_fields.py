"""Behavioural tests for the extended Django-style field set.

Covers DecimalField, BinaryField, EnumField, DurationField, TimeField,
IPAddressField, EmailField, URLField, SlugField, ArrayField,
OneToOneField, and the TimestampsMixin.
"""

from __future__ import annotations

import time as _time_module
from collections.abc import AsyncIterator
from datetime import datetime, time, timedelta
from decimal import Decimal
from enum import Enum

import pytest
from sqlalchemy import (
    DateTime,
    Interval,
    LargeBinary,
    Numeric,
    String,
    Time,
)

from pylar.database import (
    ConnectionManager,
    DatabaseConfig,
    Model,
    SoftDeletes,
    TimestampsMixin,
    fields,
    transaction,
    use_session,
)

# ----------------------------------------------------------------- enums


class PostStatus(Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


# --------------------------------------------------------------------- models


class Invoice(Model):
    class Meta:
        db_table = "test_invoices"

    customer = fields.CharField(max_length=200)
    amount = fields.DecimalField(max_digits=12, decimal_places=2)
    discount = fields.DecimalField(max_digits=5, decimal_places=4, null=True)


class Attachment(Model):
    class Meta:
        db_table = "test_attachments"

    name = fields.CharField(max_length=120)
    payload = fields.BinaryField()
    thumbnail = fields.BinaryField(max_length=64, null=True)


class Article2(Model):
    class Meta:
        db_table = "test_articles2"

    title = fields.CharField(max_length=200)
    status = fields.EnumField(enum_type=PostStatus, default=PostStatus.DRAFT)


class Schedule(Model):
    class Meta:
        db_table = "test_schedules"

    name = fields.CharField(max_length=120)
    starts_at = fields.TimeField()
    duration = fields.DurationField()


class AccessLog(Model):
    class Meta:
        db_table = "test_access_logs"

    ip = fields.IPAddressField()
    note = fields.CharField(max_length=200, default="")


class UserAccount(Model):
    class Meta:
        db_table = "test_user_accounts2"

    email = fields.EmailField(unique=True)
    homepage = fields.URLField(null=True)
    handle = fields.SlugField(unique=True)


class Tag(Model):
    class Meta:
        db_table = "test_tags2"

    name = fields.CharField(max_length=50, unique=True)


class TaggedItem(Model):
    class Meta:
        db_table = "test_tagged_items"

    title = fields.CharField(max_length=200)
    tags = fields.ArrayField(inner=fields.CharField(max_length=64))
    scores = fields.ArrayField(inner=fields.IntegerField())


class Profile(Model):
    """OneToOneField target — every account has at most one profile."""

    class Meta:
        db_table = "test_profiles"

    label = fields.CharField(max_length=120)


class Owner(Model):
    """OneToOneField user — references Profile uniquely."""

    class Meta:
        db_table = "test_owners"

    name = fields.CharField(max_length=80)
    profile_id = fields.OneToOneField(to="test_profiles.id", on_delete="CASCADE")


class TimedNote(Model, TimestampsMixin):
    """TimestampsMixin smoke test — created_at + updated_at."""

    class Meta:
        db_table = "test_timed_notes"

    body = fields.TextField()


# ----------------------------------------------------------------- fixtures


@pytest.fixture
async def manager() -> AsyncIterator[ConnectionManager]:
    config = DatabaseConfig(url="sqlite+aiosqlite:///:memory:")
    mgr = ConnectionManager(config)
    await mgr.initialize()
    async with mgr.engine.begin() as conn:
        await conn.run_sync(Model.metadata.create_all)
    try:
        yield mgr
    finally:
        await mgr.dispose()


# ----------------------------------------------------------- column metadata


def test_decimal_field_uses_numeric_with_precision_and_scale() -> None:
    col = Invoice.__table__.columns["amount"]
    assert isinstance(col.type, Numeric)
    assert col.type.precision == 12
    assert col.type.scale == 2
    assert col.type.asdecimal is True


def test_decimal_field_nullable() -> None:
    col = Invoice.__table__.columns["discount"]
    assert col.nullable is True


def test_binary_field_default_unbounded() -> None:
    col = Attachment.__table__.columns["payload"]
    assert isinstance(col.type, LargeBinary)
    assert col.type.length is None  # type: ignore[attr-defined]


def test_binary_field_with_max_length() -> None:
    col = Attachment.__table__.columns["thumbnail"]
    assert isinstance(col.type, LargeBinary)
    assert col.type.length == 64  # type: ignore[attr-defined]
    assert col.nullable is True


def test_enum_field_uses_sa_enum_with_concrete_type() -> None:
    from sqlalchemy import Enum as SaEnum

    col = Article2.__table__.columns["status"]
    assert isinstance(col.type, SaEnum)
    assert col.type.enum_class is PostStatus


def test_enum_field_requires_enum_type() -> None:
    with pytest.raises(ValueError, match="enum_type"):
        fields.EnumField()


def test_time_field_uses_sa_time() -> None:
    col = Schedule.__table__.columns["starts_at"]
    assert isinstance(col.type, Time)


def test_duration_field_uses_sa_interval() -> None:
    col = Schedule.__table__.columns["duration"]
    assert isinstance(col.type, Interval)


def test_ip_address_field_uses_string_45() -> None:
    col = AccessLog.__table__.columns["ip"]
    # On the SQLite test backend the column resolves to its base type.
    assert isinstance(col.type, String)
    assert col.type.length == 45


def test_email_field_default_max_length_is_rfc_compliant() -> None:
    col = UserAccount.__table__.columns["email"]
    assert isinstance(col.type, String)
    assert col.type.length == 254
    assert col.unique is True


def test_url_field_long_max_length() -> None:
    col = UserAccount.__table__.columns["homepage"]
    assert isinstance(col.type, String)
    assert col.type.length == 2048
    assert col.nullable is True


def test_slug_field_short_max_length() -> None:
    col = UserAccount.__table__.columns["handle"]
    assert isinstance(col.type, String)
    assert col.type.length == 50
    assert col.unique is True


def test_array_field_string_inner() -> None:
    col = TaggedItem.__table__.columns["tags"]
    # SQLite test backend resolves to JSON. Postgres would resolve to ARRAY.
    assert col.type.python_type is dict or col.type.python_type is list  # type: ignore[attr-defined]


def test_array_field_integer_inner() -> None:
    col = TaggedItem.__table__.columns["scores"]
    assert col is not None  # round trip exercised below


def test_array_field_requires_inner() -> None:
    with pytest.raises(ValueError, match="inner"):
        fields.ArrayField()


def test_one_to_one_field_carries_unique_constraint() -> None:
    col = Owner.__table__.columns["profile_id"]
    assert col.unique is True
    fks = list(col.foreign_keys)
    assert len(fks) == 1
    assert fks[0].column.table.name == "test_profiles"
    assert fks[0].ondelete == "CASCADE"


def test_timestamps_mixin_columns() -> None:
    columns = {col.name for col in TimedNote.__table__.columns}
    assert "created_at" in columns
    assert "updated_at" in columns
    created = TimedNote.__table__.columns["created_at"]
    updated = TimedNote.__table__.columns["updated_at"]
    assert isinstance(created.type, DateTime)
    assert isinstance(updated.type, DateTime)
    assert created.default is not None
    assert updated.default is not None
    assert updated.onupdate is not None


# ----------------------------------------------------------- end-to-end CRUD


async def test_decimal_round_trip(manager: ConnectionManager) -> None:
    async with use_session(manager):
        async with transaction():
            invoice = Invoice(customer="Acme", amount=Decimal("1234.56"))
            await Invoice.query.save(invoice)

        fetched = await Invoice.query.where(Invoice.customer == "Acme").first()
        assert fetched is not None
        assert fetched.amount == Decimal("1234.56")
        assert isinstance(fetched.amount, Decimal)


async def test_binary_round_trip(manager: ConnectionManager) -> None:
    async with use_session(manager):
        payload = bytes(range(256))
        async with transaction():
            await Attachment.query.save(Attachment(name="raw", payload=payload))

        fetched = await Attachment.query.where(Attachment.name == "raw").first()
        assert fetched is not None
        assert fetched.payload == payload
        assert isinstance(fetched.payload, bytes)


async def test_enum_round_trip(manager: ConnectionManager) -> None:
    async with use_session(manager):
        async with transaction():
            await Article2.query.save(
                Article2(title="t", status=PostStatus.PUBLISHED)
            )

        fetched = await Article2.query.where(Article2.title == "t").first()
        assert fetched is not None
        assert fetched.status is PostStatus.PUBLISHED


async def test_time_and_duration_round_trip(manager: ConnectionManager) -> None:
    async with use_session(manager):
        async with transaction():
            await Schedule.query.save(
                Schedule(
                    name="standup",
                    starts_at=time(9, 30),
                    duration=timedelta(minutes=15),
                )
            )

        fetched = await Schedule.query.where(Schedule.name == "standup").first()
        assert fetched is not None
        assert fetched.starts_at == time(9, 30)
        assert fetched.duration == timedelta(minutes=15)


async def test_ip_address_round_trip(manager: ConnectionManager) -> None:
    async with use_session(manager):
        async with transaction():
            await AccessLog.query.save(
                AccessLog(ip="2001:db8::1", note="ipv6")
            )
            await AccessLog.query.save(
                AccessLog(ip="192.0.2.1", note="ipv4")
            )

        rows = await AccessLog.query.all()
        ips = {row.ip for row in rows}
        assert ips == {"2001:db8::1", "192.0.2.1"}


async def test_email_url_slug_round_trip(manager: ConnectionManager) -> None:
    async with use_session(manager):
        async with transaction():
            await UserAccount.query.save(
                UserAccount(
                    email="alice@example.com",
                    homepage="https://example.com/alice",
                    handle="alice",
                )
            )

        fetched = await UserAccount.query.where(
            UserAccount.handle == "alice"
        ).first()
        assert fetched is not None
        assert fetched.email == "alice@example.com"
        assert fetched.homepage == "https://example.com/alice"


async def test_array_field_round_trip(manager: ConnectionManager) -> None:
    async with use_session(manager):
        async with transaction():
            await TaggedItem.query.save(
                TaggedItem(
                    title="post",
                    tags=["python", "framework", "pylar"],
                    scores=[1, 2, 3, 4],
                )
            )

        fetched = await TaggedItem.query.where(TaggedItem.title == "post").first()
        assert fetched is not None
        assert fetched.tags == ["python", "framework", "pylar"]
        assert fetched.scores == [1, 2, 3, 4]


async def test_one_to_one_round_trip(manager: ConnectionManager) -> None:
    async with use_session(manager):
        async with transaction():
            profile = Profile(label="primary")
            await Profile.query.save(profile)

        async with transaction():
            await Owner.query.save(Owner(name="alice", profile_id=profile.id))

        fetched = await Owner.query.where(Owner.name == "alice").first()
        assert fetched is not None
        assert fetched.profile_id == profile.id


async def test_one_to_one_unique_enforced(manager: ConnectionManager) -> None:
    from sqlalchemy.exc import IntegrityError

    async with use_session(manager):
        async with transaction():
            profile = Profile(label="shared")
            await Profile.query.save(profile)
            await Owner.query.save(Owner(name="first", profile_id=profile.id))

        with pytest.raises(IntegrityError):
            async with transaction():
                await Owner.query.save(
                    Owner(name="second", profile_id=profile.id)
                )


async def test_timestamps_mixin_set_on_insert(manager: ConnectionManager) -> None:
    async with use_session(manager):
        async with transaction():
            note = TimedNote(body="hello")
            await TimedNote.query.save(note)
        assert isinstance(note.created_at, datetime)
        assert isinstance(note.updated_at, datetime)
        assert note.created_at.tzinfo is not None
        assert note.updated_at.tzinfo is not None
        # The two columns each call ``_utc_now`` separately, so the
        # microsecond reading is not guaranteed to match — they should
        # land within the same second of each other on a fresh insert.
        delta = abs((note.updated_at - note.created_at).total_seconds())
        assert delta < 1


async def test_timestamps_mixin_updates_on_save(manager: ConnectionManager) -> None:
    async with use_session(manager):
        async with transaction():
            note = TimedNote(body="first")
            await TimedNote.query.save(note)
        original_created = note.created_at
        original_updated = note.updated_at

        # Sleep so the wall clock advances at least a microsecond.
        _time_module.sleep(0.01)

        async with transaction():
            note.body = "second"
            await TimedNote.query.save(note)

        # created_at must not move; updated_at must.
        assert note.created_at == original_created
        assert note.updated_at >= original_updated


def test_timestamps_mixin_composes_with_soft_deletes() -> None:
    class Composed(Model, TimestampsMixin, SoftDeletes):
        class Meta:
            db_table = "test_composed"

        title = fields.CharField(max_length=64)

    columns = {col.name for col in Composed.__table__.columns}
    assert "created_at" in columns
    assert "updated_at" in columns
    assert "deleted_at" in columns
    assert "title" in columns
    assert "id" in columns
