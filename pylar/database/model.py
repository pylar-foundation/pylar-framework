"""Pylar's :class:`Model` base — a typed :class:`DeclarativeBase` with a Manager attached.

Pylar deliberately does **not** hide SQLAlchemy. ``Model`` extends
``DeclarativeBase`` and supports two equally-supported ways to declare
columns:

1. Native SQLAlchemy 2.0 typed mappings::

    class User(Model):
        __tablename__ = "users"
        id: Mapped[int] = mapped_column(primary_key=True)
        email: Mapped[str]

2. Django-style field declarations from :mod:`pylar.database.fields`::

    from pylar.database import Model, fields

    class Post(Model):
        class Meta:
            db_table = "posts"

        title = fields.CharField(max_length=200)
        body = fields.TextField()
        published = fields.BooleanField(default=False)

Both styles compile down to the same SQLAlchemy mapped columns, so the
rest of the framework — :class:`Manager`, :class:`QuerySet`, observers,
soft-delete, transactions — works identically regardless of which one
the user picks. Mixing styles in the same class is allowed.

Behind the scenes a small metaclass walks the class body during
creation, converts every :class:`pylar.database.fields.Field` instance
into a ``Mapped[T]`` annotation plus a ``mapped_column(...)`` value,
adds an auto-incrementing ``id`` primary key when none is declared,
and lifts ``class Meta: db_table = "..."`` into ``__tablename__``.
The transformation happens *before* SQLAlchemy's own declarative
machinery runs, so the ORM mapping itself is untouched.

Each subclass also owns an independent list of :class:`Observer`
instances. Observers are registered through :meth:`Model.observe`
(typically from a service provider's ``boot`` phase) and inherited
along the MRO so that an observer attached to a base class also fires
for its subclasses.
"""

from __future__ import annotations

from typing import Any, ClassVar

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from pylar.database.fields import BelongsTo, Field, HasMany, HasOne, RelationshipField
from pylar.database.manager import Manager
from pylar.database.observer import Observer

# Pull the metaclass SQLAlchemy uses for DeclarativeBase. We extend it
# rather than reach for the private name (DeclarativeAttributeIntercept)
# so this code keeps working across SA point releases.
_DECLARATIVE_META: type = type(DeclarativeBase)


class _ModelMeta(_DECLARATIVE_META):  # type: ignore[misc]
    """Pre-processes Django-style field declarations before SA maps the class."""

    def __new__(
        mcs,
        name: str,
        bases: tuple[type, ...],
        namespace: dict[str, Any],
        **kwargs: Any,
    ) -> Any:
        # The Model base class itself, and any explicit ``__abstract__``
        # mixin, must not be touched — they have no table.
        if name != "Model" and not namespace.get("__abstract__", False):
            # Inherit Django-style Field instances from abstract bases
            # so they get converted to mapped_column on the concrete class.
            _inherit_abstract_fields(bases, namespace)
            _preprocess_django_fields(namespace)
            _preprocess_relationship_fields(namespace)
            _apply_meta(namespace)
        return super().__new__(mcs, name, bases, namespace, **kwargs)


def _inherit_abstract_fields(
    bases: tuple[type, ...], namespace: dict[str, Any]
) -> None:
    """Copy Django-style Field instances from abstract base classes.

    When an abstract model (``__abstract__ = True``) declares fields like
    ``name = fields.CharField(...)``, the metaclass skips field conversion
    for that class. If a concrete subclass does not redeclare those fields,
    they sit in the base's ``__dict__`` and never reach
    ``_preprocess_django_fields``.

    This function walks the MRO of the bases (in reverse so that more
    specific bases override less specific ones) and copies any
    :class:`Field` instances into *namespace* — but only if the concrete
    class has not already declared a field with the same name.
    """
    for base in reversed(bases):
        for cls in reversed(base.__mro__):
            if not getattr(cls, "__abstract__", False):
                continue
            for attr_name, value in cls.__dict__.items():
                if isinstance(value, Field) and attr_name not in namespace:
                    namespace[attr_name] = value


def _preprocess_django_fields(namespace: dict[str, Any]) -> None:
    """Convert every :class:`Field` in *namespace* into a SQLAlchemy column.

    Walks the class body, replaces each ``Field`` value with the result
    of :meth:`Field.build_mapped_column`, and inserts the matching
    ``Mapped[T]`` annotation. When no primary key is declared by either
    style, an integer ``id`` column is added automatically — same
    convention as Django's ``AutoField``.
    """
    annotations: dict[str, Any] = dict(namespace.get("__annotations__", {}))
    has_primary_key = False

    for attr_name, value in list(namespace.items()):
        if isinstance(value, Field):
            annotations[attr_name] = value.build_annotation()
            namespace[attr_name] = value.build_mapped_column()
            if value.primary_key:
                has_primary_key = True

    # The user may have already declared a PK via the native SA syntax;
    # in that case there's nothing to add. We don't have a reliable way
    # to introspect arbitrary mapped_column expressions for `primary_key`,
    # so the heuristic is "if `id` is already in the namespace or in the
    # annotations, leave it alone". Anyone explicitly using a non-`id`
    # PK column should rely on the Field-based path or set
    # ``__pylar_has_pk__ = True`` to opt out of the auto column.
    if not has_primary_key:
        if "id" in annotations or "id" in namespace:
            has_primary_key = True
        if namespace.get("__pylar_has_pk__", False):
            has_primary_key = True

    if not has_primary_key:
        annotations["id"] = Mapped[int]
        namespace["id"] = mapped_column(primary_key=True, autoincrement=True)

    namespace["__annotations__"] = annotations


def _preprocess_relationship_fields(namespace: dict[str, Any]) -> None:
    """Convert :class:`RelationshipField` instances into ``relationship()`` calls.

    Unlike :func:`_preprocess_django_fields` which handles column fields,
    this function processes :class:`BelongsTo`, :class:`HasMany`, and
    :class:`HasOne` into SQLAlchemy ``relationship()`` declarations.
    """
    from sqlalchemy.orm import Mapped, relationship

    annotations: dict[str, Any] = namespace.get("__annotations__", {})

    for attr_name, value in list(namespace.items()):
        if not isinstance(value, RelationshipField):
            continue

        if isinstance(value, BelongsTo):
            _process_belongs_to(attr_name, value, namespace, annotations)
        elif isinstance(value, HasMany):
            kwargs: dict[str, Any] = {
                "lazy": value.lazy,
                "cascade": value.cascade,
            }
            if value.back_populates:
                kwargs["back_populates"] = value.back_populates
            # Use string annotation so SA resolves the forward reference.
            annotations[attr_name] = Mapped[list[Any]]
            namespace[attr_name] = relationship(value.model, **kwargs)
        elif isinstance(value, HasOne):
            kwargs = {
                "uselist": False,
                "lazy": value.lazy,
                "cascade": value.cascade,
            }
            if value.back_populates:
                kwargs["back_populates"] = value.back_populates
            annotations[attr_name] = Mapped[Any]
            namespace[attr_name] = relationship(value.model, **kwargs)

    namespace["__annotations__"] = annotations


def _process_belongs_to(
    attr_name: str,
    field: BelongsTo,
    namespace: dict[str, Any],
    annotations: dict[str, Any],
) -> None:
    """Expand a :class:`BelongsTo` into a FK column + relationship."""
    import uuid as _uuid

    from sqlalchemy import ForeignKey as SaForeignKey
    from sqlalchemy import Integer, Uuid
    from sqlalchemy.orm import Mapped, mapped_column, relationship

    # Create FK column: attr_name + "_id"
    fk_col_name = f"{attr_name}_id"

    sa_type = Uuid() if field.as_uuid else Integer()
    py_type: type = _uuid.UUID if field.as_uuid else int

    if field.null:
        annotations[fk_col_name] = Mapped[py_type | None]  # type: ignore[valid-type]
    else:
        annotations[fk_col_name] = Mapped[py_type]  # type: ignore[valid-type]

    col_kwargs: dict[str, Any] = {"nullable": field.null}
    namespace[fk_col_name] = mapped_column(
        sa_type, SaForeignKey(field.to, ondelete=field.on_delete), **col_kwargs,
    )

    # Create relationship attribute
    rel_kwargs: dict[str, Any] = {"lazy": "raise"}
    if field.back_populates:
        rel_kwargs["back_populates"] = field.back_populates
    annotations[attr_name] = Mapped[Any]
    namespace[attr_name] = relationship(field.model, **rel_kwargs)


def _apply_meta(namespace: dict[str, Any]) -> None:
    """Lift settings from the inner ``Meta`` class into the namespace.

    Currently only :attr:`Meta.db_table` is honoured — additional
    settings (indexes, ordering, abstract flags) can be added here as
    pylar grows.
    """
    meta = namespace.get("Meta")
    if meta is None:
        return
    db_table = getattr(meta, "db_table", None)
    if db_table is not None and "__tablename__" not in namespace:
        namespace["__tablename__"] = db_table


class Model(DeclarativeBase, metaclass=_ModelMeta):
    """Base class for every pylar-managed entity."""

    # The annotation is wide on purpose: each concrete subclass receives its
    # own narrowly-typed manager via __init_subclass__. Users that want full
    # static typing on ``query`` can re-declare it on the subclass:
    #
    #     class User(Model):
    #         query: ClassVar[Manager["User"]]
    #
    # but the runtime value is correct without that override.
    query: ClassVar[Manager[Any]]

    #: Per-class observer list. Each subclass owns its own list — the base
    #: list on ``Model`` itself is intentionally never populated, because
    #: registering an observer on ``Model`` would mean firing it for every
    #: entity in the application, which is almost never what users want.
    _observers: ClassVar[list[Observer[Any]]] = []

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if cls.__dict__.get("__abstract__", False):
            return
        cls.query = Manager(cls)
        # Give each concrete subclass its own observer list rather than
        # mutating one inherited from a parent.
        if "_observers" not in cls.__dict__:
            cls._observers = []

    @classmethod
    def observe(cls, observer: Observer[Any]) -> None:
        """Attach an observer instance to this model class.

        Typically called from a service provider's ``boot`` phase so that the
        observer can be constructed via the container with its own
        dependencies::

            class AppServiceProvider(ServiceProvider):
                async def boot(self, container: Container) -> None:
                    User.observe(container.make(UserObserver))
        """
        if "_observers" not in cls.__dict__:
            cls._observers = []
        cls._observers.append(observer)

    @classmethod
    def observers(cls) -> tuple[Observer[Any], ...]:
        """Return every observer attached to this class or any of its parents.

        The order is leaf-to-root: an observer registered directly on the
        subclass runs before one inherited from a base. This matches the
        intuition that more specific code overrides more general code.
        """
        collected: list[Observer[Any]] = []
        for klass in cls.__mro__:
            klass_observers = klass.__dict__.get("_observers")
            if klass_observers:
                collected.extend(klass_observers)
        return tuple(collected)
