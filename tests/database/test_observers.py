"""Tests for :class:`Observer` lifecycle and :meth:`Model.observe` registration."""

from __future__ import annotations

import pytest

from pylar.database import Observer, transaction
from tests.database.conftest import User


class _TraceObserver(Observer[User]):
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    async def saving(self, instance: User) -> None:
        self.events.append(("saving", instance.email))

    async def creating(self, instance: User) -> None:
        self.events.append(("creating", instance.email))

    async def created(self, instance: User) -> None:
        self.events.append(("created", instance.email))

    async def updating(self, instance: User) -> None:
        self.events.append(("updating", instance.email))

    async def updated(self, instance: User) -> None:
        self.events.append(("updated", instance.email))

    async def saved(self, instance: User) -> None:
        self.events.append(("saved", instance.email))

    async def deleting(self, instance: User) -> None:
        self.events.append(("deleting", instance.email))

    async def deleted(self, instance: User) -> None:
        self.events.append(("deleted", instance.email))


@pytest.fixture(autouse=True)
def _reset_observers() -> None:
    # Each test wires its own observers; clear between tests so registrations
    # don't leak across the suite.
    User._observers = []  # type: ignore[attr-defined]


pytestmark = pytest.mark.usefixtures("session")


async def test_create_fires_saving_creating_created_saved_in_order() -> None:
    observer = _TraceObserver()
    User.observe(observer)

    async with transaction():
        new_user = User(email="dave@example.com", name="Dave")
        await User.query.save(new_user)

    assert [name for name, _ in observer.events] == [
        "saving",
        "creating",
        "created",
        "saved",
    ]
    assert all(email == "dave@example.com" for _, email in observer.events)


async def test_update_fires_updating_and_updated() -> None:
    observer = _TraceObserver()
    User.observe(observer)

    target = await User.query.where(User.email == "alice@example.com").first()
    assert target is not None

    async with transaction():
        target.name = "Alice Updated"
        await User.query.save(target)

    names = [name for name, _ in observer.events]
    assert "updating" in names
    assert "updated" in names
    assert "creating" not in names
    assert "created" not in names


async def test_delete_fires_deleting_then_deleted() -> None:
    observer = _TraceObserver()
    User.observe(observer)

    target = await User.query.where(User.email == "bob@example.com").first()
    assert target is not None

    async with transaction():
        await User.query.delete(target)

    assert [name for name, _ in observer.events] == [
        ("deleting"),
        ("deleted"),
    ]


async def test_multiple_observers_all_run() -> None:
    a = _TraceObserver()
    b = _TraceObserver()
    User.observe(a)
    User.observe(b)

    async with transaction():
        await User.query.save(User(email="multi@example.com", name="Multi"))

    assert len(a.events) == 4
    assert len(b.events) == 4


async def test_bulk_queryset_delete_does_not_fire_observers() -> None:
    observer = _TraceObserver()
    User.observe(observer)

    async with transaction():
        await User.query.where(User.active.is_(False)).delete()

    assert observer.events == []


async def test_observers_classmethod_collects_along_mro() -> None:
    observer = _TraceObserver()
    User.observe(observer)
    assert observer in User.observers()
