"""Behavioural tests for :class:`pylar.foundation.Container`."""

from __future__ import annotations

from typing import Protocol

import pytest

from pylar.foundation import (
    BindingError,
    CircularDependencyError,
    Container,
    ResolutionError,
)

# --------------------------------------------------------------------- fixtures


class Logger:
    def __init__(self) -> None:
        self.lines: list[str] = []


class Repository:
    def __init__(self, logger: Logger) -> None:
        self.logger = logger


class Service:
    def __init__(self, repo: Repository, logger: Logger) -> None:
        self.repo = repo
        self.logger = logger


class Mailer(Protocol):
    def send(self, to: str) -> None: ...


class SmtpMailer:
    def send(self, to: str) -> None:
        return None


class CycleA:
    def __init__(self, b: CycleB) -> None:
        self.b = b


class CycleB:
    def __init__(self, a: CycleA) -> None:
        self.a = a


class NeedsUntyped:
    def __init__(self, x: object) -> None:
        self.x = x


class NeedsKwargs:
    def __init__(self, logger: Logger, **opts: object) -> None:
        self.logger = logger
        self.opts = opts


class RedisStore:
    pass


class FileStore:
    pass


# ----------------------------------------------------------------------- tests


def test_make_auto_wires_constructor_dependencies() -> None:
    container = Container()
    service = container.make(Service)

    assert isinstance(service, Service)
    assert isinstance(service.repo, Repository)
    assert isinstance(service.logger, Logger)
    # transient by default — repo's logger and the top-level logger are distinct.
    assert service.logger is not service.repo.logger


def test_singleton_returns_same_instance() -> None:
    container = Container()
    container.singleton(Logger, Logger)

    first = container.make(Logger)
    second = container.make(Logger)
    assert first is second


def test_singleton_is_shared_across_dependents() -> None:
    container = Container()
    container.singleton(Logger, Logger)

    service = container.make(Service)
    assert service.logger is service.repo.logger


def test_instance_binding_returns_exact_object() -> None:
    container = Container()
    sentinel = Logger()
    container.instance(Logger, sentinel)

    assert container.make(Logger) is sentinel


def test_protocol_without_binding_raises() -> None:
    container = Container()
    with pytest.raises(BindingError, match="Protocol"):
        container.make(Mailer)  # type: ignore[type-abstract]


def test_protocol_resolves_after_binding() -> None:
    container = Container()
    container.bind(Mailer, SmtpMailer)  # type: ignore[type-abstract]

    mailer = container.make(Mailer)  # type: ignore[type-abstract]
    assert isinstance(mailer, SmtpMailer)


def test_factory_binding_invoked_each_resolve() -> None:
    container = Container()
    counter = {"n": 0}

    def make_logger() -> Logger:
        counter["n"] += 1
        return Logger()

    container.bind(Logger, make_logger)

    container.make(Logger)
    container.make(Logger)
    assert counter["n"] == 2


def test_circular_dependency_detected() -> None:
    container = Container()
    with pytest.raises(CircularDependencyError):
        container.make(CycleA)


def test_missing_type_hint_raises_resolution_error() -> None:
    container = Container()
    with pytest.raises(ResolutionError, match="no type hint"):
        container.make(NeedsUntyped)


def test_var_kwargs_in_constructor_forbidden() -> None:
    container = Container()
    with pytest.raises(ResolutionError, match="variadic keywords"):
        container.make(NeedsKwargs)


def test_call_resolves_function_parameters() -> None:
    container = Container()

    def handler(service: Service) -> Service:
        return service

    result = container.call(handler)
    assert isinstance(result, Service)


def test_call_overrides_take_precedence_over_container() -> None:
    container = Container()
    custom_logger = Logger()
    custom_logger.lines.append("override")

    def handler(logger: Logger) -> Logger:
        return logger

    result = container.call(handler, overrides={Logger: custom_logger})
    assert result is custom_logger


def test_tagged_resolves_every_member() -> None:
    container = Container()
    container.tag([RedisStore, FileStore], "cache.stores")

    stores = container.tagged("cache.stores")
    assert len(stores) == 2
    assert any(isinstance(s, RedisStore) for s in stores)
    assert any(isinstance(s, FileStore) for s in stores)


def test_scoped_binding_shared_within_scope() -> None:
    container = Container()
    container.scoped(Logger, Logger)

    with container.scope():
        a = container.make(Logger)
        b = container.make(Logger)
        assert a is b

    with container.scope():
        c = container.make(Logger)
        assert c is not a


def test_scoped_binding_outside_scope_raises() -> None:
    container = Container()
    container.scoped(Logger, Logger)

    with pytest.raises(ResolutionError, match="no scope is active"):
        container.make(Logger)


def test_has_reflects_explicit_bindings_only() -> None:
    container = Container()
    assert not container.has(Logger)
    container.bind(Logger, Logger)
    assert container.has(Logger)
