"""Resolved route handler — either a plain async function or a controller method.

Pylar accepts two handler shapes when a route is registered:

* A standalone ``async def`` function::

      async def index(request: Request) -> Response: ...
      router.get("/", index)

* An unbound method on a controller class::

      class UserController:
          def __init__(self, repo: UserRepository) -> None: ...
          async def show(self, request: Request, user_id: int) -> Response: ...

      router.get("/users/{user_id:int}", UserController.show)

The :class:`Action` hierarchy normalises both shapes into a single ``invoke``
contract that the route compiler can call from the ASGI endpoint.

In addition to plain DI, the action layer recognises any handler parameter
typed as a :class:`pylar.validation.RequestDTO` subclass. At registration
time the framework scans the handler's signature once, caches the names and
types of those DTO parameters, and at invoke time it parses the request body
into each one before delegating to :meth:`Container.call`.
"""

from __future__ import annotations

import inspect
import sys
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, cast, get_type_hints

from pylar.foundation.container import Container
from pylar.http.request import Request
from pylar.http.response import Response
from pylar.routing.exceptions import InvalidHandlerError
from pylar.validation.dto import CookieDTO, HeaderDTO, RequestDTO
from pylar.validation.resolver import (
    resolve_cookie_dto,
    resolve_dto,
    resolve_header_dto,
)
from pylar.validation.upload import UploadFile

#: Anything callable that returns a :class:`Response` (or an awaitable of one).
Handler = Callable[..., Awaitable[Response]]


class Action(ABC):
    """A handler that can be invoked through the container."""

    @abstractmethod
    async def invoke(
        self,
        container: Container,
        request: Request,
        path_params: dict[str, object],
    ) -> Response:
        """Run the handler and return its response."""

    @staticmethod
    def from_handler(handler: Handler) -> Action:
        """Classify *handler* and wrap it in the appropriate :class:`Action` subclass."""
        if not callable(handler):
            raise InvalidHandlerError(f"Handler {handler!r} is not callable")
        if not inspect.iscoroutinefunction(handler):
            raise InvalidHandlerError(
                f"Handler {handler.__qualname__} must be defined with `async def`"
            )

        owner = _detect_controller(handler)
        scan = _scan_handler_params(handler)
        if owner is None:
            return FunctionAction(
                func=handler,
                dto_params=scan.dto_params,
                model_params=scan.model_params,
                header_params=scan.header_params,
                cookie_params=scan.cookie_params,
                upload_params=scan.upload_params,
            )

        method_name = handler.__name__
        return ControllerAction(
            controller_cls=owner,
            method_name=method_name,
            dto_params=scan.dto_params,
            model_params=scan.model_params,
            header_params=scan.header_params,
            cookie_params=scan.cookie_params,
            upload_params=scan.upload_params,
        )


@dataclass(frozen=True, slots=True)
class FunctionAction(Action):
    """A standalone async function — no controller instance involved."""

    func: Handler
    dto_params: dict[str, type[RequestDTO]] = field(default_factory=dict)
    model_params: dict[str, type[Any]] = field(default_factory=dict)
    header_params: dict[str, type[HeaderDTO]] = field(default_factory=dict)
    cookie_params: dict[str, type[CookieDTO]] = field(default_factory=dict)
    upload_params: tuple[str, ...] = ()

    async def invoke(
        self,
        container: Container,
        request: Request,
        path_params: dict[str, object],
    ) -> Response:
        params = await _build_call_params(
            self.dto_params,
            self.model_params,
            self.header_params,
            self.cookie_params,
            self.upload_params,
            request,
            path_params,
        )
        result = container.call(
            self.func,
            overrides={Request: request},
            params=params,
        )
        return _auto_serialise(await result)


@dataclass(frozen=True, slots=True)
class ControllerAction(Action):
    """A method on a controller class. The class is resolved per request."""

    controller_cls: type[Any]
    method_name: str
    dto_params: dict[str, type[RequestDTO]] = field(default_factory=dict)
    model_params: dict[str, type[Any]] = field(default_factory=dict)
    header_params: dict[str, type[HeaderDTO]] = field(default_factory=dict)
    cookie_params: dict[str, type[CookieDTO]] = field(default_factory=dict)
    upload_params: tuple[str, ...] = ()

    async def invoke(
        self,
        container: Container,
        request: Request,
        path_params: dict[str, object],
    ) -> Response:
        controller = container.make(self.controller_cls)
        bound_method = cast(Handler, getattr(controller, self.method_name))
        params = await _build_call_params(
            self.dto_params,
            self.model_params,
            self.header_params,
            self.cookie_params,
            self.upload_params,
            request,
            path_params,
        )
        result = container.call(
            bound_method,
            overrides={Request: request},
            params=params,
        )
        return _auto_serialise(await result)


# ------------------------------------------------------------------ scanning


@dataclass(frozen=True, slots=True)
class _HandlerScan:
    dto_params: dict[str, type[RequestDTO]]
    model_params: dict[str, type[Any]]
    header_params: dict[str, type[HeaderDTO]]
    cookie_params: dict[str, type[CookieDTO]]
    upload_params: tuple[str, ...]


_EMPTY_SCAN = _HandlerScan({}, {}, {}, {}, ())


def _scan_handler_params(handler: Handler) -> _HandlerScan:
    """Classify every parameter of *handler* by its annotation type.

    Recognised parameter shapes:

    * ``RequestDTO`` subclass — parsed from body / query at invoke time.
    * ``HeaderDTO`` subclass — parsed from ``request.headers``.
    * ``CookieDTO`` subclass — parsed from ``request.cookies``.
    * ``UploadFile`` — pulled from ``request.form()`` under the matching
      parameter name.
    * ``pylar.database.Model`` subclass — resolved through
      ``Model.query.get(path_param)``; missing rows surface as 404.

    Each scan happens once at registration time and the results live on
    the cached :class:`Action` instance, so per-request work is a dict
    merge plus the actual I/O for each binding.
    """
    try:
        hints = get_type_hints(handler)
    except Exception:
        return _EMPTY_SCAN

    dto_params: dict[str, type[RequestDTO]] = {}
    model_params: dict[str, type[Any]] = {}
    header_params: dict[str, type[HeaderDTO]] = {}
    cookie_params: dict[str, type[CookieDTO]] = {}
    upload_params: list[str] = []

    signature = inspect.signature(handler)
    for name in signature.parameters:
        if name in ("self", "cls"):
            continue
        annotation = hints.get(name)
        if not isinstance(annotation, type):
            continue
        if issubclass(annotation, HeaderDTO):
            header_params[name] = annotation
        elif issubclass(annotation, CookieDTO):
            cookie_params[name] = annotation
        elif issubclass(annotation, RequestDTO):
            dto_params[name] = annotation
        elif issubclass(annotation, UploadFile):
            upload_params.append(name)
        elif _is_model_class(annotation):
            model_params[name] = annotation

    return _HandlerScan(
        dto_params=dto_params,
        model_params=model_params,
        header_params=header_params,
        cookie_params=cookie_params,
        upload_params=tuple(upload_params),
    )


def _is_model_class(annotation: type) -> bool:
    """Return ``True`` when *annotation* inherits :class:`pylar.database.Model`.

    The import is local on purpose: the routing module is layered
    *below* the database module in the dependency graph, so importing
    Model at module load time would create a cycle. Walking through the
    function on every registration is fast enough — the routing layer
    only inspects each handler once per process.
    """
    try:
        from pylar.database.model import Model
    except ImportError:
        return False
    return issubclass(annotation, Model)


async def _build_call_params(
    dto_params: dict[str, type[RequestDTO]],
    model_params: dict[str, type[Any]],
    header_params: dict[str, type[HeaderDTO]],
    cookie_params: dict[str, type[CookieDTO]],
    upload_params: tuple[str, ...],
    request: Request,
    path_params: dict[str, object],
) -> dict[str, object]:
    """Merge path parameters with freshly-resolved DTO / model / file bindings."""
    if not (
        dto_params
        or model_params
        or header_params
        or cookie_params
        or upload_params
    ):
        return path_params
    merged: dict[str, object] = dict(path_params)
    for name, dto_cls in dto_params.items():
        merged[name] = await resolve_dto(dto_cls, request)
    for name, header_cls in header_params.items():
        merged[name] = await resolve_header_dto(header_cls, request)
    for name, cookie_cls in cookie_params.items():
        merged[name] = await resolve_cookie_dto(cookie_cls, request)
    if upload_params:
        form = await request.form()
        for name in upload_params:
            value = form.get(name)
            if not isinstance(value, UploadFile):
                from pylar.validation.exceptions import ValidationError

                raise ValidationError(
                    [
                        {
                            "loc": [name],
                            "msg": "missing or non-file form field",
                            "type": "upload.missing",
                        }
                    ]
                )
            merged[name] = value
    for name, model_cls in model_params.items():
        # Match handler param to path param: try exact name first,
        # then "{name}_id" (Laravel convention: `post: Post` matches
        # path param `{post}` or `{post_id}`).
        pk_value: object | None = None
        if name in path_params:
            pk_value = path_params[name]
        elif f"{name}_id" in path_params:
            pk_value = path_params[f"{name}_id"]
        if pk_value is not None:
            merged[name] = await _resolve_model_binding(model_cls, pk_value)
    return merged


async def _resolve_model_binding(model_cls: type[Any], primary_key: object) -> Any:
    """Fetch *model_cls* by *primary_key* or raise :class:`NotFound`.

    Translates pylar's :class:`RecordNotFoundError` into the HTTP layer's
    :class:`NotFound` so the route compiler renders it as a 404 without
    any per-controller boilerplate.
    """
    from pylar.database.exceptions import RecordNotFoundError
    from pylar.http import NotFound

    try:
        return await model_cls.query.get(primary_key)
    except RecordNotFoundError as exc:
        # Generic message — model class name and primary key are
        # internal details that aid attacker reconnaissance.
        raise NotFound("Resource not found") from exc


# ----------------------------------------------------------------- introspection


def _detect_controller(handler: Handler) -> type[Any] | None:
    """Return the owner class of *handler* if it is a method on a top-level class.

    Detection rules:

    * The function's ``__qualname__`` must be exactly ``ClassName.method_name``
      (no nested classes, no closures).
    * The class must be importable from the function's defining module under
      the same name.
    * The class's ``__dict__`` must point to *handler*, guarding against
      qualname spoofing or rebinding.

    Returns ``None`` for plain top-level functions and for any case the loader
    cannot prove safe — those are then treated as :class:`FunctionAction`.
    """
    qualname = getattr(handler, "__qualname__", "")
    if "." not in qualname:
        return None

    parts = qualname.split(".")
    if len(parts) != 2 or "<locals>" in qualname:
        return None

    cls_name, method_name = parts
    if method_name != handler.__name__:
        return None

    module_name = getattr(handler, "__module__", None)
    if module_name is None:
        return None
    module = sys.modules.get(module_name)
    if module is None:
        return None

    cls = getattr(module, cls_name, None)
    if not isinstance(cls, type):
        return None

    if cls.__dict__.get(method_name) is not handler:
        return None

    return cls


def _auto_serialise(result: object) -> Response:
    """Wrap a pydantic-shaped controller return value in JsonResponse.

    Pass-through for already-built :class:`Response` instances; wraps
    :class:`pydantic.BaseModel` (and homogeneous lists of them) into a
    :class:`JsonResponse`. Foreign return types fall through and trip
    the Starlette type error so mistakes are surfaced early.
    """
    from pydantic import BaseModel

    from pylar.http.response import JsonResponse

    if isinstance(result, Response):
        return result
    if isinstance(result, BaseModel):
        return JsonResponse(content=result.model_dump(mode="json"))
    if isinstance(result, list) and result and all(
        isinstance(item, BaseModel) for item in result
    ):
        return JsonResponse(
            content=[item.model_dump(mode="json") for item in result]
        )
    # Fall through — the compiler's downstream machinery will raise
    # if the return value is not a Response-compatible object.
    return result  # type: ignore[return-value]
