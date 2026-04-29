"""Typed request validation: pydantic-backed DTOs auto-resolved by the router."""

from pylar.validation.dto import CookieDTO, HeaderDTO, RequestDTO
from pylar.validation.exceptions import MalformedBodyError, ValidationError
from pylar.validation.model_dto import model_dto
from pylar.validation.renderer import (
    DefaultValidationRenderer,
    ValidationErrorRenderer,
)
from pylar.validation.resolver import (
    resolve_cookie_dto,
    resolve_dto,
    resolve_header_dto,
)
from pylar.validation.upload import UploadFile

__all__ = [
    "CookieDTO",
    "DefaultValidationRenderer",
    "HeaderDTO",
    "MalformedBodyError",
    "RequestDTO",
    "UploadFile",
    "ValidationError",
    "ValidationErrorRenderer",
    "model_dto",
    "resolve_cookie_dto",
    "resolve_dto",
    "resolve_header_dto",
]
