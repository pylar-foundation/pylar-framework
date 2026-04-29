"""Behavioural tests for :class:`Gate` and :class:`Policy`."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from pylar.auth import AuthorizationError, Gate, Policy


@dataclass
class _User:
    id: int
    is_admin: bool = False


@dataclass
class _Post:
    id: int
    author_id: int


class _PostPolicy(Policy[_Post]):
    async def view_any(self, user: _User) -> bool:  # type: ignore[override]
        return True

    async def view(self, user: _User, instance: _Post) -> bool:  # type: ignore[override]
        return True

    async def update(self, user: _User, instance: _Post) -> bool:  # type: ignore[override]
        return user.is_admin or user.id == instance.author_id

    async def delete(self, user: _User, instance: _Post) -> bool:  # type: ignore[override]
        return user.is_admin


@pytest.fixture
def gate() -> Gate:
    g = Gate()
    g.policy(_Post, _PostPolicy())
    return g


# ----------------------------------------------------------------- policy path


async def test_policy_view_any_uses_class_lookup(gate: Gate) -> None:
    user = _User(id=1)
    assert await gate.allows(user, "view_any", _Post)


async def test_policy_update_grants_to_owner(gate: Gate) -> None:
    user = _User(id=1)
    own_post = _Post(id=10, author_id=1)
    assert await gate.allows(user, "update", own_post)


async def test_policy_update_denies_to_other_user(gate: Gate) -> None:
    user = _User(id=2)
    foreign_post = _Post(id=11, author_id=1)
    assert await gate.allows(user, "update", foreign_post) is False


async def test_policy_delete_grants_to_admin(gate: Gate) -> None:
    admin = _User(id=99, is_admin=True)
    post = _Post(id=10, author_id=1)
    assert await gate.allows(admin, "delete", post)


async def test_unknown_ability_on_known_policy_returns_false(gate: Gate) -> None:
    user = _User(id=1)
    post = _Post(id=10, author_id=1)
    assert await gate.allows(user, "publish", post) is False


# ----------------------------------------------------------------- ability path


async def test_define_ability_callback() -> None:
    gate = Gate()

    async def access_admin(user: _User) -> bool:
        return user.is_admin

    gate.define("access-admin", access_admin)

    assert await gate.allows(_User(id=1, is_admin=True), "access-admin")
    assert not await gate.allows(_User(id=2, is_admin=False), "access-admin")


# ------------------------------------------------------------------- authorize


async def test_authorize_raises_when_denied(gate: Gate) -> None:
    user = _User(id=2)
    post = _Post(id=10, author_id=1)
    with pytest.raises(AuthorizationError) as exc_info:
        await gate.authorize(user, "update", post)
    assert exc_info.value.ability == "update"


async def test_authorize_succeeds_silently_when_allowed(gate: Gate) -> None:
    user = _User(id=1)
    post = _Post(id=10, author_id=1)
    await gate.authorize(user, "update", post)


async def test_denies_is_inverse_of_allows(gate: Gate) -> None:
    user = _User(id=2)
    post = _Post(id=10, author_id=1)
    assert await gate.denies(user, "update", post) is True
    assert await gate.denies(_User(id=1), "update", post) is False
