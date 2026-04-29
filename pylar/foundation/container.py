"""Typed IoC container with constructor auto-wiring."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from typing import Any, TypeVar, cast

from pylar.foundation.binding import Binding, Concrete, Scope
from pylar.foundation.exceptions import (
    BindingError,
    CircularDependencyError,
    ResolutionError,
)
from pylar.foundation.resolver import inspect_callable

T = TypeVar("T")


class Container:
    """A typed service container.

    The container resolves abstract types to concrete instances by inspecting
    constructor type hints. There are no string identifiers, no ``**kwargs``,
    and no implicit globals — every binding is an explicit ``type → type``
    mapping with a declared lifetime scope.

    Three lifetime scopes are supported:

    * ``Scope.TRANSIENT`` — a fresh instance on every :meth:`make` call (default).
    * ``Scope.SINGLETON`` — one instance for the lifetime of the container.
    * ``Scope.SCOPED`` — one instance per active :meth:`scope` context.
    """

    def __init__(self) -> None:
        self._bindings: dict[type[Any], Binding[Any]] = {}
        self._singletons: dict[type[Any], object] = {}
        self._scope_stack: list[dict[type[Any], object]] = []
        self._tags: dict[str, list[type[Any]]] = {}
        self._resolving: list[type[Any]] = []

    # ------------------------------------------------------------------ binding

    def bind[T](
        self,
        abstract: type[T],
        concrete: Concrete[T],
        *,
        scope: Scope = Scope.TRANSIENT,
    ) -> None:
        """Register a mapping from *abstract* to *concrete*."""
        self._bindings[abstract] = Binding(abstract=abstract, concrete=concrete, scope=scope)

    def singleton[T](self, abstract: type[T], concrete: Concrete[T]) -> None:
        """Register *concrete* as a singleton instance of *abstract*."""
        self.bind(abstract, concrete, scope=Scope.SINGLETON)
        # Drop any cached singleton so a re-bind takes effect on next resolve.
        self._singletons.pop(abstract, None)

    def scoped[T](self, abstract: type[T], concrete: Concrete[T]) -> None:
        """Register *concrete* as a scope-bound instance of *abstract*."""
        self.bind(abstract, concrete, scope=Scope.SCOPED)

    def instance[T](self, abstract: type[T], instance: T) -> None:
        """Register an already-constructed *instance* as the singleton for *abstract*."""
        def _factory() -> T:
            return instance

        self._bindings[abstract] = Binding(
            abstract=abstract, concrete=_factory, scope=Scope.SINGLETON
        )
        self._singletons[abstract] = instance

    def has(self, abstract: type[Any]) -> bool:
        """Return ``True`` if *abstract* has an explicit binding."""
        return abstract in self._bindings

    # ------------------------------------------------------------------ tagging

    def tag(self, abstracts: Sequence[type[Any]], tag: str) -> None:
        """Group several abstracts under a string *tag* for later bulk resolution."""
        bucket = self._tags.setdefault(tag, [])
        for abstract in abstracts:
            if abstract not in bucket:
                bucket.append(abstract)

    def tagged(self, tag: str) -> list[object]:
        """Resolve every abstract previously registered under *tag*."""
        return [self.make(abstract) for abstract in self._tags.get(tag, [])]

    def tagged_types(self, tag: str) -> tuple[type[Any], ...]:
        """Return the abstracts grouped under *tag* without instantiating them.

        Used by the console kernel to enumerate commands cheaply: only the
        command that actually matches the user's argv is constructed.
        """
        return tuple(self._tags.get(tag, []))

    # ------------------------------------------------------------------ scoping

    @contextmanager
    def scope(self) -> Iterator[None]:
        """Open a scope context — :class:`Scope.SCOPED` bindings live until exit."""
        self._scope_stack.append({})
        try:
            yield
        finally:
            self._scope_stack.pop()

    # ------------------------------------------------------------------ resolve

    def make[T](self, abstract: type[T]) -> T:
        """Resolve *abstract* to a fully-constructed instance."""
        if abstract in self._resolving:
            # The resolution stack is unwound by the `finally` blocks of the
            # outer make() calls — do not touch it here.
            raise CircularDependencyError([*self._resolving, abstract])

        # 1. Cached singleton?
        if abstract in self._singletons:
            return cast(T, self._singletons[abstract])

        # 2. Cached in current scope?
        if self._scope_stack:
            current = self._scope_stack[-1]
            if abstract in current:
                return cast(T, current[abstract])

        binding = self._bindings.get(abstract)

        self._resolving.append(abstract)
        try:
            if binding is None:
                instance = self._auto_resolve(abstract)
                # Implicit auto-resolution is always transient — never cached.
                return cast(T, instance)

            instance = self._instantiate(binding.concrete)

            if binding.scope is Scope.SINGLETON:
                self._singletons[abstract] = instance
            elif binding.scope is Scope.SCOPED:
                if not self._scope_stack:
                    raise ResolutionError(
                        f"{abstract.__qualname__} is bound as SCOPED but no scope is active"
                    )
                self._scope_stack[-1][abstract] = instance
        finally:
            self._resolving.pop()

        return cast(T, instance)

    def _auto_resolve(self, abstract: type[Any]) -> object:
        """Try to instantiate *abstract* directly when no binding exists."""
        if not isinstance(abstract, type):
            raise BindingError(
                f"{abstract!r} is not a class and has no binding — bind it in a ServiceProvider"
            )
        if _is_protocol(abstract):
            raise BindingError(
                f"{abstract.__qualname__} is a Protocol with no binding. "
                f"Register a concrete implementation via container.bind()."
            )
        if inspect.isabstract(abstract):
            raise BindingError(
                f"{abstract.__qualname__} is abstract and has no binding. "
                f"Register a concrete subclass via container.bind()."
            )
        return self._build(abstract)

    def _instantiate(self, concrete: Concrete[Any]) -> object:
        """Build a concrete: either a class (auto-wired) or a zero-arg factory."""
        if isinstance(concrete, type):
            return self._build(concrete)
        # Zero-arg factory by contract.
        return concrete()

    def _build(self, cls: type[Any]) -> object:
        """Construct *cls*, resolving every constructor parameter from the container.

        Parameters are passed by **name**, never by position, so
        constructors with keyword-only arguments work the same way as
        the positional form.

        Resolution rules:

        1. No annotation, no default → impossible — :func:`inspect_callable`
           refuses to register such a parameter.
        2. No annotation, has default → leave it to the constructor.
        3. Has annotation, type is *bound* in the container → resolve via
           :meth:`make`. Bound bindings win over the constructor default.
        4. Has annotation, type is *not* bound, has default → leave it
           to the constructor. This lets users write
           ``def __init__(self, *, cookie_name: str = "pylar_csrf")``
           without the container blindly trying to instantiate ``str``.
        5. Has annotation, type is not bound, no default → recurse into
           :meth:`make`, which will either auto-build the class or raise
           a clear ``BindingError``.
        """
        init = cls.__init__
        # `object.__init__` accepts no arguments — short-circuit to avoid
        # introspection of slot wrappers.
        if init is object.__init__:
            return cls()

        params = inspect_callable(init)
        kwargs: dict[str, object] = {}
        for param in params:
            if param.annotation is None:
                # Rule 2: untyped + default → constructor default wins.
                continue
            if param.has_default and not self.has(param.annotation):
                # Rule 4: typed + default + unbound → constructor wins.
                continue
            # Rules 3 and 5: resolve from the container.
            kwargs[param.name] = self.make(param.annotation)
        return cls(**kwargs)

    # --------------------------------------------------------------------- call

    def call[T](
        self,
        target: Callable[..., T],
        *,
        overrides: dict[type[Any], object] | None = None,
        params: dict[str, object] | None = None,
    ) -> T:
        """Invoke *target* with each parameter resolved from the container.

        Resolution order for every parameter:

        1. ``params`` — runtime values keyed by parameter *name* (used by the
           router to pass path parameters into controller methods).
        2. ``overrides`` — runtime values keyed by parameter *type* (used by
           the router to inject the current :class:`Request`).
        3. The container itself, via :meth:`make`.
        """
        overrides = overrides or {}
        named = params or {}
        resolved = inspect_callable(target)
        args: list[object] = []
        for parameter in resolved:
            if parameter.name in named:
                args.append(named[parameter.name])
                continue
            if parameter.annotation is not None and parameter.annotation in overrides:
                args.append(overrides[parameter.annotation])
                continue
            if parameter.annotation is None:
                args.append(parameter.default)
                continue
            args.append(self.make(parameter.annotation))
        return target(*args)


def _is_protocol(cls: type[Any]) -> bool:
    return bool(getattr(cls, "_is_protocol", False))
