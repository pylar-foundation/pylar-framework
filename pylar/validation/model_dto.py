"""Generate a :class:`RequestDTO` from a :class:`~pylar.database.Model`.

``model_dto`` introspects a Model's mapped columns via SQLAlchemy's
inspection API and produces a pydantic-based RequestDTO whose fields
mirror the model columns with sensible defaults:

* Primary-key columns are excluded by default.
* Nullable columns become ``Optional[T]`` with ``default=None``.
* Columns with a server default get ``default=None`` in the DTO so
  the client may omit them.
* Relationship attributes are always skipped.

Usage::

    from pylar.validation import model_dto

    class UserCreateDTO(model_dto(User, exclude=["id", "created_at"])):
        pass

    class UserUpdateDTO(model_dto(User, include=["name", "email"])):
        pass

The returned class is a standard :class:`RequestDTO` subclass and works
with the router's auto-resolver exactly like a hand-written DTO.
"""

from __future__ import annotations

from typing import Any

from pydantic import create_model

from pylar.validation.dto import RequestDTO

# Mapping from SQLAlchemy type class names to Python types.
_SA_TYPE_MAP: dict[str, type] = {
    "Integer": int,
    "BigInteger": int,
    "SmallInteger": int,
    "Float": float,
    "Numeric": float,
    "String": str,
    "Text": str,
    "Boolean": bool,
    "DateTime": str,
    "Date": str,
    "Time": str,
    "Interval": str,
    "Uuid": str,
    "JSON": dict,
    "JSONB": dict,
    "LargeBinary": bytes,
    "Enum": str,
    "ARRAY": list,
}


def model_dto(
    model: type,
    *,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
    name: str | None = None,
) -> type[RequestDTO]:
    """Create a :class:`RequestDTO` subclass from a Model's columns.

    Parameters
    ----------
    model:
        A :class:`~pylar.database.Model` subclass to introspect.
    include:
        If given, only these column names are included. Mutually
        exclusive with *exclude*.
    exclude:
        Column names to skip. Primary-key columns are always excluded
        unless explicitly listed in *include*.
    name:
        Class name for the generated DTO. Defaults to
        ``"{Model.__name__}DTO"``.
    """
    from sqlalchemy import inspect as sa_inspect

    if include is not None and exclude is not None:
        raise ValueError("Cannot specify both `include` and `exclude`")

    mapper: Any = sa_inspect(model)
    exclude_set = set(exclude or [])
    include_set = set(include) if include is not None else None

    field_definitions: dict[str, Any] = {}

    for column in mapper.columns:
        col_name: str = column.key

        # Skip PKs unless explicitly included.
        if column.primary_key and (include_set is None or col_name not in include_set):
            continue

        if include_set is not None and col_name not in include_set:
            continue
        if col_name in exclude_set:
            continue

        # Resolve Python type from SA column type.
        sa_type_name = type(column.type).__name__
        py_type = _SA_TYPE_MAP.get(sa_type_name, Any)

        # Nullable → Optional with default None.
        if column.nullable:
            field_definitions[col_name] = (py_type | None, None)
        elif column.default is not None or column.server_default is not None:
            field_definitions[col_name] = (py_type | None, None)
        else:
            field_definitions[col_name] = (py_type, ...)

    dto_name = name or f"{model.__name__}DTO"
    return create_model(dto_name, __base__=RequestDTO, **field_definitions)
