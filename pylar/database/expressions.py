"""Composable, model-aware predicate helpers — :class:`F` and :class:`Q`.

The QuerySet layer accepts SQLAlchemy ``ColumnElement[bool]`` instances
directly, which is precise but verbose for predicates that need to be
combined dynamically — every branch has to drill into the model class to
fetch the column, and ``or_`` / ``and_`` chains turn into nested calls
that drown out the intent.

:class:`F` and :class:`Q` are sugar that compile down to the same SA
expressions the QuerySet already understands, but they let the caller
write predicates that read like Python and combine with the usual
boolean operators::

    qs = User.query.where(Q(active=True) | Q(role="admin"))
    qs = User.query.where(F("login_count") > 10)
    qs = User.query.where(~Q(banned=True) & Q(email__icontains="@corp.com"))

Both :class:`F` and :class:`Q` are *deferred*: they remember the column
name and the operator but they do not touch the model class until
:meth:`Q.compile` is called by ``QuerySet.where``. That keeps them
reusable across models — a single ``Q(active=True)`` expression compiles
correctly against any model that exposes an ``active`` column.

The supported lookup operators on the kwargs form follow Django's
spelling so they read identically to anyone coming from that ecosystem:
``eq`` (default), ``ne``, ``gt``, ``ge``, ``lt``, ``le``, ``in``,
``contains``, ``icontains``, ``startswith``, ``endswith``, ``isnull``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from sqlalchemy import ColumnElement, and_, not_, or_, true

# ---------------------------------------------------------------------- F


class F:
    """Deferred reference to a column on the bound model.

    Comparison operators applied to an :class:`F` produce a :class:`Q`
    so the result is composable with the rest of the predicate algebra::

        Q(active=True) & (F("login_count") > 10)

    The column lookup is resolved against the model that owns the
    QuerySet at ``where`` time, so the same :class:`F` can be reused
    across queries against different (compatible) models.
    """

    __slots__ = ("_name",)

    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def resolve(self, model: type[Any]) -> Any:
        col = getattr(model, self._name, None)
        if col is None:
            raise AttributeError(
                f"{model.__name__} has no column or attribute {self._name!r}"
            )
        return col

    # ---- comparisons → Q -------------------------------------------------

    def __eq__(self, other: object) -> Q:  # type: ignore[override]
        return Q._from_node(_Cmp(self, "eq", other))

    def __ne__(self, other: object) -> Q:  # type: ignore[override]
        return Q._from_node(_Cmp(self, "ne", other))

    def __gt__(self, other: object) -> Q:
        return Q._from_node(_Cmp(self, "gt", other))

    def __ge__(self, other: object) -> Q:
        return Q._from_node(_Cmp(self, "ge", other))

    def __lt__(self, other: object) -> Q:
        return Q._from_node(_Cmp(self, "lt", other))

    def __le__(self, other: object) -> Q:
        return Q._from_node(_Cmp(self, "le", other))

    def __hash__(self) -> int:
        return hash(("F", self._name))

    def __repr__(self) -> str:
        return f"F({self._name!r})"


# ---------------------------------------------------------------------- nodes


class _Node:
    """Internal predicate tree node — compile to a SA expression."""

    def compile(self, model: type[Any]) -> ColumnElement[bool]:  # pragma: no cover - abstract
        raise NotImplementedError


class _Cmp(_Node):
    def __init__(self, left: F, op: str, right: object) -> None:
        self._left = left
        self._op = op
        self._right = right

    def compile(self, model: type[Any]) -> ColumnElement[bool]:
        column = self._left.resolve(model)
        right = self._right
        if isinstance(right, F):
            right = right.resolve(model)
        return _apply(column, self._op, right)


class _Kwargs(_Node):
    def __init__(self, kwargs: dict[str, object]) -> None:
        self._kwargs = kwargs

    def compile(self, model: type[Any]) -> ColumnElement[bool]:
        clauses: list[ColumnElement[bool]] = []
        for raw_key, value in self._kwargs.items():
            field, _, op = raw_key.partition("__")
            column = getattr(model, field, None)
            if column is None:
                raise AttributeError(
                    f"{model.__name__} has no column or attribute {field!r}"
                )
            if isinstance(value, F):
                value = value.resolve(model)
            clauses.append(_apply(column, op or "eq", value))
        if not clauses:
            # Empty Q matches everything — render as a tautology so the
            # SQLAlchemy compiler still has a real predicate to attach.
            return true()
        if len(clauses) == 1:
            return clauses[0]
        return and_(*clauses)


class _And(_Node):
    def __init__(self, left: _Node, right: _Node) -> None:
        self._left = left
        self._right = right

    def compile(self, model: type[Any]) -> ColumnElement[bool]:
        return and_(self._left.compile(model), self._right.compile(model))


class _Or(_Node):
    def __init__(self, left: _Node, right: _Node) -> None:
        self._left = left
        self._right = right

    def compile(self, model: type[Any]) -> ColumnElement[bool]:
        return or_(self._left.compile(model), self._right.compile(model))


class _Not(_Node):
    def __init__(self, child: _Node) -> None:
        self._child = child

    def compile(self, model: type[Any]) -> ColumnElement[bool]:
        return not_(self._child.compile(model))


# ---------------------------------------------------------------------- Q


class Q:
    """Composable predicate, combinable with ``|``, ``&`` and ``~``.

    Two construction forms are supported:

    * **Kwargs form** — ``Q(active=True, role="admin")`` builds a
      conjunction of equality checks against the named columns. Lookup
      suffixes (``Q(name__icontains="al")``) follow Django's spelling.
    * **Comparison form** — :class:`F` produces a :class:`Q` from any
      comparison operator (see :class:`F`).

    Compilation is deferred until :meth:`compile` is called by
    ``QuerySet.where``. The model class is supplied at that point, so
    a Q expression can be reused across queries.
    """

    __slots__ = ("_node",)

    def __init__(self, **kwargs: object) -> None:
        self._node: _Node = _Kwargs(kwargs)

    @classmethod
    def _from_node(cls, node: _Node) -> Q:
        instance = cls.__new__(cls)
        instance._node = node
        return instance

    def compile(self, model: type[Any]) -> ColumnElement[bool]:
        return self._node.compile(model)

    def __or__(self, other: Q) -> Q:
        return Q._from_node(_Or(self._node, other._node))

    def __and__(self, other: Q) -> Q:
        return Q._from_node(_And(self._node, other._node))

    def __invert__(self) -> Q:
        return Q._from_node(_Not(self._node))

    def __repr__(self) -> str:
        return f"<Q {self._node.__class__.__name__}>"


# ----------------------------------------------------------- operator dispatch


def _bool(expr: Any) -> ColumnElement[bool]:
    return cast(ColumnElement[bool], expr)


def _op_eq(c: Any, v: Any) -> ColumnElement[bool]:
    return _bool(c.is_(None) if v is None else c == v)


def _op_ne(c: Any, v: Any) -> ColumnElement[bool]:
    return _bool(c.is_not(None) if v is None else c != v)


def _op_isnull(c: Any, v: Any) -> ColumnElement[bool]:
    return _bool(c.is_(None) if v else c.is_not(None))


_OPS: dict[str, Callable[[Any, Any], ColumnElement[bool]]] = {
    "eq": _op_eq,
    "ne": _op_ne,
    "gt": lambda c, v: _bool(c > v),
    "ge": lambda c, v: _bool(c >= v),
    "lt": lambda c, v: _bool(c < v),
    "le": lambda c, v: _bool(c <= v),
    "in": lambda c, v: _bool(c.in_(tuple(v))),
    "contains": lambda c, v: _bool(c.contains(v, autoescape=True)),
    "icontains": lambda c, v: _bool(c.ilike(f"%{_escape_like(v)}%", escape="\\")),
    "startswith": lambda c, v: _bool(c.startswith(v, autoescape=True)),
    "endswith": lambda c, v: _bool(c.endswith(v, autoescape=True)),
    "isnull": _op_isnull,
}


def _escape_like(value: str) -> str:
    """Escape ``%``, ``_``, and ``\\`` in a LIKE operand so they match literally."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _apply(column: Any, op: str, value: Any) -> ColumnElement[bool]:
    try:
        handler = _OPS[op]
    except KeyError as exc:
        raise ValueError(
            f"Unknown lookup operator {op!r}. Supported: {sorted(_OPS)}"
        ) from exc
    return handler(column, value)
