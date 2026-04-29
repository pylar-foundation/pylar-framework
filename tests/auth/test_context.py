"""Tests for :func:`current_user` and :func:`authenticate_as`."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from pylar.auth import (
    NoCurrentUserError,
    authenticate_as,
    current_user,
    current_user_or_none,
)


@dataclass
class _FakeUser:
    auth_identifier: int
    auth_password_hash: str = ""


def test_current_user_outside_scope_raises() -> None:
    with pytest.raises(NoCurrentUserError, match="No authenticated user"):
        current_user()


def test_current_user_inside_scope_returns_user() -> None:
    user = _FakeUser(auth_identifier=1)
    with authenticate_as(user):
        assert current_user() is user


def test_authenticate_as_clears_on_exit() -> None:
    user = _FakeUser(auth_identifier=1)
    with authenticate_as(user):
        pass
    assert current_user_or_none() is None


def test_anonymous_scope_supported_via_none() -> None:
    with authenticate_as(None):
        assert current_user_or_none() is None
        with pytest.raises(NoCurrentUserError):
            current_user()


def test_nested_scopes_restore_outer_user() -> None:
    outer = _FakeUser(auth_identifier=1)
    inner = _FakeUser(auth_identifier=2)
    with authenticate_as(outer):
        with authenticate_as(inner):
            assert current_user() is inner
        assert current_user() is outer
    assert current_user_or_none() is None
