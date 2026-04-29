"""Django-style field declarations for :class:`pylar.database.Model`.

These classes are a thin, typed facade over SQLAlchemy's
``mapped_column``. The :class:`Model` metaclass walks the class body
during creation, finds every :class:`Field` instance, asks it for the
matching ``Mapped[T]`` annotation and ``mapped_column(...)`` call, and
hands the result to SQLAlchemy's normal declarative machinery.

That gives users the visual ergonomics they expect from Django::

    from pylar.database import Model, fields

    class Post(Model):
        class Meta:
            db_table = "posts"

        title = fields.CharField(max_length=200)
        body = fields.TextField()
        published = fields.BooleanField(default=False)
        created_at = fields.DateTimeField(auto_now_add=True)

while still producing standard SQLAlchemy-typed mappings underneath, so
``Post.query``, observers, soft-delete, transactions, and every other
piece of the framework keep working without any special-casing.

Mixing styles is allowed — the metaclass leaves existing
``Mapped[int] = mapped_column(...)`` declarations untouched, so a
single model can use Field instances for the boring columns and drop
into raw SQLAlchemy for anything exotic.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any, ClassVar

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    Integer,
    Interval,
    LargeBinary,
    Numeric,
    String,
    Text,
    Time,
    Uuid,
)
from sqlalchemy import Enum as SaEnum
from sqlalchemy import ForeignKey as SaForeignKey
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

#: Sentinel that distinguishes "no default" from "default is None".
MISSING: Any = object()


@dataclass(kw_only=True)
class Field:
    """Base class for every Django-style field declaration.

    The five attributes are common to every column type and map onto
    the matching ``mapped_column`` keyword arguments. Subclasses add
    type-specific options (e.g. ``max_length`` on :class:`CharField`)
    and override :attr:`python_type` and :meth:`sa_type` to declare
    their SQLAlchemy column type.
    """

    null: bool = False
    default: Any = MISSING
    unique: bool = False
    primary_key: bool = False
    index: bool = False
    #: Human-readable column description. Persisted on the SQL
    #: column's ``COMMENT`` attribute so DBAs can read it in the
    #: catalog, and surfaced by the admin panel as the column's
    #: display label when no explicit translation key is defined
    #: (see :meth:`pylar_admin.serializer.field_label`).
    comment: str | None = None

    #: The Python type the column maps to. Subclasses set this so the
    #: metaclass can build the correct ``Mapped[T]`` annotation.
    python_type: ClassVar[type] = object

    # ----------------------------------------------------------- subclass hooks

    def sa_type(self) -> Any:
        """Return the SQLAlchemy type instance for this field."""
        raise NotImplementedError(
            f"{type(self).__name__}.sa_type() must be implemented"
        )

    # ----------------------------------------------------------- metaclass API

    def build_annotation(self) -> Any:
        """Return the value that goes into ``__annotations__`` for this column.

        ``Mapped[X]`` is constructed at runtime from ``self.python_type``.
        mypy cannot follow that — its `valid-type` check expects every
        type argument to be a literal type expression — but SQLAlchemy's
        own runtime introspection accepts the dynamic generic alias just
        fine, which is the contract that actually matters here.
        """
        py_type = self.python_type
        if self.null:
            return Mapped[py_type | None]  # type: ignore[valid-type]
        return Mapped[py_type]  # type: ignore[valid-type]

    def build_mapped_column(self) -> Any:
        """Return the ``mapped_column(...)`` value that replaces this Field."""
        return mapped_column(self.sa_type(), **self._mapped_column_kwargs())

    def _mapped_column_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"nullable": self.null}
        if self.unique:
            kwargs["unique"] = True
        if self.primary_key:
            kwargs["primary_key"] = True
        if self.index:
            kwargs["index"] = True
        if self.default is not MISSING:
            kwargs["default"] = self.default
        if self.comment is not None:
            kwargs["comment"] = self.comment
        return kwargs


# --------------------------------------------------------------- numerics


@dataclass(kw_only=True)
class IntegerField(Field):
    python_type: ClassVar[type] = int

    def sa_type(self) -> Any:
        return Integer()


@dataclass(kw_only=True)
class BigIntegerField(Field):
    python_type: ClassVar[type] = int

    def sa_type(self) -> Any:
        return BigInteger()


@dataclass(kw_only=True)
class FloatField(Field):
    python_type: ClassVar[type] = float

    def sa_type(self) -> Any:
        return Float()


@dataclass(kw_only=True)
class DecimalField(Field):
    """Exact-decimal column for money and other fixed-precision values.

    ``max_digits`` is the total number of significant digits stored;
    ``decimal_places`` is how many of them sit to the right of the
    decimal point. The Python type is :class:`decimal.Decimal`, never
    ``float`` — that is the whole point of using this column over a
    :class:`FloatField`.
    """

    max_digits: int = 10
    decimal_places: int = 2
    python_type: ClassVar[type] = Decimal

    def sa_type(self) -> Any:
        return Numeric(self.max_digits, self.decimal_places, asdecimal=True)


@dataclass(kw_only=True)
class AutoField(Field):
    """Integer primary key — pylar's equivalent of Django's ``AutoField``.

    Always declares an auto-incrementing integer column with
    ``primary_key=True``. Use :class:`PrimaryKeyField` when you want
    the same role for a UUID column.
    """

    primary_key: bool = True
    python_type: ClassVar[type] = int

    def sa_type(self) -> Any:
        return Integer()

    def build_mapped_column(self) -> Any:
        kwargs = self._mapped_column_kwargs()
        kwargs.setdefault("autoincrement", True)
        return mapped_column(self.sa_type(), **kwargs)


@dataclass(kw_only=True)
class PrimaryKeyField(Field):
    """A primary-key column that can be either integer or UUID.

    With the default ``as_uuid=False`` it produces an auto-incrementing
    integer PK identical to :class:`AutoField`. With ``as_uuid=True`` it
    produces a :class:`sqlalchemy.Uuid` column whose default factory is
    :func:`uuid.uuid4`, so client code receives a fully-populated id at
    instance construction time without an extra round trip.

    The Python type of the column adapts to the flag — ``int`` or
    :class:`uuid.UUID` — and :meth:`build_annotation` constructs the
    matching ``Mapped[T]`` annotation accordingly.
    """

    primary_key: bool = True
    as_uuid: bool = False
    python_type: ClassVar[type] = int  # build_annotation overrides for uuid

    def sa_type(self) -> Any:
        if self.as_uuid:
            return Uuid()
        return Integer()

    def build_annotation(self) -> Any:
        py_type: type = uuid.UUID if self.as_uuid else int
        if self.null:
            return Mapped[py_type | None]  # type: ignore[valid-type]
        return Mapped[py_type]  # type: ignore[valid-type]

    def build_mapped_column(self) -> Any:
        kwargs = self._mapped_column_kwargs()
        if self.as_uuid:
            kwargs.setdefault("default", uuid.uuid4)
        else:
            kwargs.setdefault("autoincrement", True)
        return mapped_column(self.sa_type(), **kwargs)


# --------------------------------------------------------------- strings


@dataclass(kw_only=True)
class CharField(Field):
    max_length: int = 255
    python_type: ClassVar[type] = str

    def sa_type(self) -> Any:
        return String(self.max_length)


@dataclass(kw_only=True)
class TextField(Field):
    python_type: ClassVar[type] = str

    def sa_type(self) -> Any:
        return Text()


@dataclass(kw_only=True)
class EmailField(CharField):
    """Email column — a CharField with the standard RFC length cap.

    Does **not** validate the format at the column level. Bind the
    field to a :class:`pylar.validation.RequestDTO` with a pydantic
    ``EmailStr`` annotation to get input validation; this class only
    fixes the column shape.
    """

    max_length: int = 254  # RFC 5321 maximum mailbox length


@dataclass(kw_only=True)
class URLField(CharField):
    """URL column — wider than CharField for long links."""

    max_length: int = 2048


@dataclass(kw_only=True)
class SlugField(CharField):
    """Short slug column — typically used as a URL fragment."""

    max_length: int = 50


@dataclass(kw_only=True)
class BinaryField(Field):
    """Binary blob column over :class:`sqlalchemy.LargeBinary`.

    ``max_length`` is forwarded to the SA type when supplied; leaving
    it as :data:`None` produces an unbounded BYTEA / BLOB.
    """

    max_length: int | None = None
    python_type: ClassVar[type] = bytes

    def sa_type(self) -> Any:
        return LargeBinary(self.max_length) if self.max_length else LargeBinary()


@dataclass(kw_only=True)
class IPAddressField(Field):
    """IP address column — ``String(45)`` portable, ``INET`` on Postgres.

    The python value is a plain :class:`str` so application code stays
    portable. Use :func:`ipaddress.ip_address` at the call site if you
    need a parsed object.
    """

    python_type: ClassVar[type] = str

    def sa_type(self) -> Any:
        return String(45).with_variant(INET(), "postgresql")


# --------------------------------------------------------------- booleans


@dataclass(kw_only=True)
class BooleanField(Field):
    python_type: ClassVar[type] = bool

    def sa_type(self) -> Any:
        return Boolean()


@dataclass(kw_only=True)
class EnumField(Field):
    """Typed enum column over :class:`sqlalchemy.Enum`.

    ``enum_type`` is the :class:`enum.Enum` subclass that defines the
    allowed values. SQLAlchemy emits a real database CHECK / native
    ENUM constraint so the column rejects values outside that set at
    insert time, not just at the application boundary.
    """

    enum_type: type[Enum] = Enum
    python_type: ClassVar[type] = object  # build_annotation overrides

    def __post_init__(self) -> None:
        if self.enum_type is Enum:
            raise ValueError(
                "EnumField requires an `enum_type` argument pointing at a "
                "concrete enum.Enum subclass"
            )

    def sa_type(self) -> Any:
        return SaEnum(self.enum_type)

    def build_annotation(self) -> Any:
        py_type: type = self.enum_type
        if self.null:
            return Mapped[py_type | None]  # type: ignore[valid-type]
        return Mapped[py_type]  # type: ignore[valid-type]


# ------------------------------------------------------- date / datetime


@dataclass(kw_only=True)
class DateTimeField(Field):
    timezone: bool = True
    auto_now_add: bool = False
    python_type: ClassVar[type] = datetime

    def sa_type(self) -> Any:
        return DateTime(timezone=self.timezone)

    def build_mapped_column(self) -> Any:
        if self.auto_now_add and self.default is MISSING:
            self.default = _utc_now
        return super().build_mapped_column()


@dataclass(kw_only=True)
class DateField(Field):
    python_type: ClassVar[type] = date

    def sa_type(self) -> Any:
        return Date()


@dataclass(kw_only=True)
class TimeField(Field):
    """Time-of-day column without a date component."""

    python_type: ClassVar[type] = time

    def sa_type(self) -> Any:
        return Time()


@dataclass(kw_only=True)
class DurationField(Field):
    """Interval column mapped to :class:`datetime.timedelta`."""

    python_type: ClassVar[type] = timedelta

    def sa_type(self) -> Any:
        return Interval()


def _utc_now() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------- json


@dataclass(kw_only=True)
class JSONField(Field):
    """A portable JSON column. Uses ``sqlalchemy.JSON`` on every backend."""

    python_type: ClassVar[type] = dict

    def sa_type(self) -> Any:
        return JSON()


@dataclass(kw_only=True)
class JSONBField(Field):
    """JSONB on PostgreSQL, plain JSON everywhere else.

    The column type is built with
    ``JSON().with_variant(JSONB(), "postgresql")`` so the user gets the
    full GIN-indexable JSONB experience on Postgres without breaking the
    SQLite test suite that the rest of the framework relies on.
    """

    python_type: ClassVar[type] = dict

    def sa_type(self) -> Any:
        return JSON().with_variant(JSONB(), "postgresql")


@dataclass(kw_only=True)
class ArrayField(Field):
    """List column.

    Uses Postgres ``ARRAY`` natively when available and falls back to
    portable JSON storage on every other backend, the same approach
    :class:`JSONBField` takes for objects. The element type is taken
    from another :class:`Field` instance — typically a primitive like
    :class:`IntegerField` or :class:`CharField`::

        tags = fields.ArrayField(inner=fields.CharField(max_length=64))
    """

    inner: Field | None = None
    python_type: ClassVar[type] = list

    def __post_init__(self) -> None:
        if self.inner is None:
            raise ValueError(
                "ArrayField requires an `inner` Field describing the element type "
                "(e.g. inner=fields.CharField(max_length=64))"
            )

    def sa_type(self) -> Any:
        assert self.inner is not None  # __post_init__ guarantees this
        inner_sa_type = self.inner.sa_type()
        return JSON().with_variant(PG_ARRAY(inner_sa_type), "postgresql")


# ---------------------------------------------------------------------- uuid


@dataclass(kw_only=True)
class UuidField(Field):
    """A standalone UUID column.

    Uses :class:`sqlalchemy.Uuid`, which adapts at compile time:
    native ``UUID`` on PostgreSQL, ``CHAR(32)`` / ``BINARY(16)`` on
    backends without a UUID type. Python-side the value is always a
    :class:`uuid.UUID` instance.

    Set ``auto=True`` to populate the column with :func:`uuid.uuid4`
    when no explicit default is supplied — useful for non-PK UUID
    columns such as public-facing identifiers that the application
    generates client-side.
    """

    auto: bool = False
    python_type: ClassVar[type] = uuid.UUID

    def sa_type(self) -> Any:
        return Uuid()

    def build_mapped_column(self) -> Any:
        if self.auto and self.default is MISSING:
            self.default = uuid.uuid4
        return super().build_mapped_column()


# ----------------------------------------------------------- relationships


@dataclass(kw_only=True)
class ForeignKey(Field):
    """Foreign-key column referencing another table.

    ``to`` is the SQL ``table.column`` reference (e.g. ``"users.id"``)
    or a SQLAlchemy ``Column`` object. ``on_delete`` is forwarded to
    the SQL ``ON DELETE`` clause; valid values are ``"CASCADE"``,
    ``"SET NULL"``, ``"SET DEFAULT"``, ``"RESTRICT"``, ``"NO ACTION"``.

    Set ``as_uuid=True`` when the referenced table uses a UUID primary
    key (typically declared via ``PrimaryKeyField(as_uuid=True)``).
    The FK column then uses :class:`sqlalchemy.Uuid` instead of
    :class:`Integer` and is typed as :class:`uuid.UUID` on the Python
    side, so the type system catches a mismatch between an int FK and
    a uuid PK at the model definition level.
    """

    to: str = ""
    on_delete: str = "RESTRICT"
    as_uuid: bool = False
    python_type: ClassVar[type] = int  # build_annotation overrides for uuid

    def __post_init__(self) -> None:
        if not self.to:
            raise ValueError(
                "ForeignKey requires a non-empty `to` argument "
                "(e.g. to=\"users.id\")"
            )

    def sa_type(self) -> Any:
        if self.as_uuid:
            return Uuid()
        return Integer()

    def build_annotation(self) -> Any:
        py_type: type = uuid.UUID if self.as_uuid else int
        if self.null:
            return Mapped[py_type | None]  # type: ignore[valid-type]
        return Mapped[py_type]  # type: ignore[valid-type]

    def build_mapped_column(self) -> Any:
        return mapped_column(
            self.sa_type(),
            SaForeignKey(self.to, ondelete=self.on_delete),
            **self._mapped_column_kwargs(),
        )


@dataclass(kw_only=True)
class OneToOneField(ForeignKey):
    """A foreign key with a uniqueness constraint.

    Identical to :class:`ForeignKey` in every other respect — the
    referenced row may still be ``None`` when ``null=True`` is set,
    and ``as_uuid`` works the same way. Pylar does not yet wire up
    a SQLAlchemy ``relationship(uselist=False)`` automatically; users
    that want the navigation attribute add it manually next to the
    column declaration.
    """

    unique: bool = True


# --------------------------------------------------------- relationship fields


class RelationshipField:
    """Marker base for relationship declarations (not a column field).

    Relationship fields are processed by the metaclass separately from
    :class:`Field` instances — they emit ``relationship()`` calls
    instead of ``mapped_column()`` calls.
    """


@dataclass(kw_only=True)
class BelongsTo(RelationshipField):
    """Declare a many-to-one relationship alongside its foreign key.

    Combines a FK column and a navigation ``relationship()`` in a
    single declaration::

        class Comment(Model):
            __tablename__ = "comments"
            post = fields.BelongsTo(
                to="posts.id",
                model="Post",
                on_delete="CASCADE",
            )

    This creates both ``comment.post_id`` (the FK column) and
    ``comment.post`` (the SQLAlchemy relationship). The column name
    is derived from the attribute name + ``_id`` suffix.

    ``back_populates`` is the attribute name on the *other* model
    that refers back to this side. If omitted no ``back_populates``
    is emitted and the reverse side must be configured manually (or
    via :class:`HasMany` / :class:`HasOne`).
    """

    to: str = ""
    model: str = ""
    on_delete: str = "RESTRICT"
    as_uuid: bool = False
    null: bool = False
    back_populates: str = ""

    def __post_init__(self) -> None:
        if not self.to:
            raise ValueError("BelongsTo requires a `to` argument (e.g. to=\"users.id\")")
        if not self.model:
            raise ValueError("BelongsTo requires a `model` argument (e.g. model=\"User\")")


@dataclass(kw_only=True)
class HasMany(RelationshipField):
    """Declare a one-to-many reverse relationship::

        class Post(Model):
            __tablename__ = "posts"
            comments = fields.HasMany(model="Comment", back_populates="post")

    This emits ``relationship("Comment", back_populates="post")`` on
    the Post model. No column is created — the FK lives on Comment.
    """

    model: str = ""
    back_populates: str = ""
    cascade: str = "all, delete-orphan"
    lazy: str = "raise"

    def __post_init__(self) -> None:
        if not self.model:
            raise ValueError("HasMany requires a `model` argument")


@dataclass(kw_only=True)
class HasOne(RelationshipField):
    """Declare a one-to-one reverse relationship::

        class User(Model):
            __tablename__ = "users"
            profile = fields.HasOne(model="Profile", back_populates="user")

    Like :class:`HasMany` but with ``uselist=False``.
    """

    model: str = ""
    back_populates: str = ""
    cascade: str = "all, delete-orphan"
    lazy: str = "raise"

    def __post_init__(self) -> None:
        if not self.model:
            raise ValueError("HasOne requires a `model` argument")
