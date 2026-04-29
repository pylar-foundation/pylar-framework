"""Tests for model_dto() — auto-generation of RequestDTO from Model."""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from pylar.database import Model, fields
from pylar.validation import RequestDTO, model_dto


class DtoTestModel(Model):
    __tablename__ = "dto_test_models"
    title = fields.CharField(max_length=200)
    body = fields.TextField(null=True)
    published = fields.BooleanField(default=False)
    view_count = fields.IntegerField(default=0)


def test_model_dto_creates_request_dto_subclass() -> None:
    dto_cls = model_dto(DtoTestModel)
    assert issubclass(dto_cls, RequestDTO)


def test_model_dto_excludes_pk_by_default() -> None:
    dto_cls = model_dto(DtoTestModel)
    field_names = set(dto_cls.model_fields.keys())
    assert "id" not in field_names


def test_model_dto_includes_non_pk_columns() -> None:
    dto_cls = model_dto(DtoTestModel)
    field_names = set(dto_cls.model_fields.keys())
    assert "title" in field_names
    assert "body" in field_names
    assert "published" in field_names


def test_model_dto_nullable_field_is_optional() -> None:
    dto_cls = model_dto(DtoTestModel)
    # body is nullable — should accept None and have default None
    instance = dto_cls(title="Hello")
    assert instance.body is None


def test_model_dto_required_field_raises_on_missing() -> None:
    dto_cls = model_dto(DtoTestModel)
    with pytest.raises(PydanticValidationError):
        dto_cls()  # title is required


def test_model_dto_exclude_param() -> None:
    dto_cls = model_dto(DtoTestModel, exclude=["body", "view_count"])
    field_names = set(dto_cls.model_fields.keys())
    assert "body" not in field_names
    assert "view_count" not in field_names
    assert "title" in field_names


def test_model_dto_include_param() -> None:
    dto_cls = model_dto(DtoTestModel, include=["title", "body"])
    field_names = set(dto_cls.model_fields.keys())
    assert field_names == {"title", "body"}


def test_model_dto_include_and_exclude_raises() -> None:
    with pytest.raises(ValueError, match="Cannot specify both"):
        model_dto(DtoTestModel, include=["title"], exclude=["body"])


def test_model_dto_custom_name() -> None:
    dto_cls = model_dto(DtoTestModel, name="CreateModelInput")
    assert dto_cls.__name__ == "CreateModelInput"


def test_model_dto_default_name() -> None:
    dto_cls = model_dto(DtoTestModel)
    assert dto_cls.__name__ == "DtoTestModelDTO"


def test_model_dto_validates_types() -> None:
    dto_cls = model_dto(DtoTestModel)
    instance = dto_cls(title="Hello", body="World")
    assert instance.title == "Hello"
    assert instance.body == "World"
