"""OpenAPI 3.1 generator driven by the router and type hints (ADR-0007 phase 7b).

The generator walks :class:`pylar.routing.Router`'s compiled routes,
introspects each handler's signature, and emits an OpenAPI 3.1 document
as a plain ``dict[str, Any]`` ready to be JSON-serialised.

Everything the generator needs already lives in the typed layers:

* The :class:`pylar.routing.Route` knows path + method + name.
* The :class:`pylar.routing.action.Action` knows the resolved handler
  and its ``dto_params`` / ``model_params`` / header / cookie / upload
  maps — populated by the router's own scanner at registration time.
* The handler's return annotation tells the schema for 2xx responses.

Because the source of truth is the handler signature and the pydantic
DTOs it already uses, the spec cannot drift from the code: the moment a
controller's annotation lies the spec is wrong, which is strictly
better than a hand-maintained YAML fixture.
"""

from __future__ import annotations

import inspect
import re
from typing import Any, get_args, get_origin

from pydantic import BaseModel

from pylar.api.pagination import Page
from pylar.routing.action import ControllerAction, FunctionAction
from pylar.routing.route import Route
from pylar.routing.router import Router

# Matches Starlette-style path converters: `{post_id:int}` → name=`post_id`, type=`int`
_PATH_PARAM_RE = re.compile(r"\{(?P<name>[^:}]+)(?::(?P<type>[^}]+))?\}")

_PATH_TYPE_MAP: dict[str, dict[str, str]] = {
    "int": {"type": "integer"},
    "float": {"type": "number"},
    "str": {"type": "string"},
    "path": {"type": "string"},
    "uuid": {"type": "string", "format": "uuid"},
}


def generate_openapi(
    router: Router,
    *,
    title: str = "Pylar API",
    version: str = "0.0.1",
    description: str | None = None,
    servers: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Walk *router* and return an OpenAPI 3.1 document as a dict.

    *servers* is an ordered tuple of base URLs (``https://api.example.com``)
    to publish under the top-level ``servers`` block. OpenAPI-aware
    clients (Swagger UI dropdown, generated SDKs) use it to target
    production / staging / local without rewriting the spec.
    """
    spec: dict[str, Any] = {
        "openapi": "3.1.0",
        "info": {"title": title, "version": version},
        "paths": {},
        "components": {"schemas": {}},
    }
    if description is not None:
        spec["info"]["description"] = description
    if servers:
        spec["servers"] = [{"url": url} for url in servers]

    schemas: dict[str, Any] = spec["components"]["schemas"]

    for route in router.routes():
        openapi_path, path_params = _convert_path(route.path)
        operation = _build_operation(route, path_params, schemas)
        spec["paths"].setdefault(openapi_path, {})[route.method.lower()] = operation

    return spec


# ------------------------------------------------------------- path handling


def _convert_path(path: str) -> tuple[str, list[dict[str, Any]]]:
    """Convert ``/posts/{post_id:int}`` → ``/posts/{post_id}`` + param specs."""
    params: list[dict[str, Any]] = []

    def replace(match: re.Match[str]) -> str:
        name = match.group("name")
        type_hint = match.group("type") or "str"
        schema = _PATH_TYPE_MAP.get(type_hint, {"type": "string"}).copy()
        params.append({
            "name": name,
            "in": "path",
            "required": True,
            "schema": schema,
        })
        return "{" + name + "}"

    openapi_path = _PATH_PARAM_RE.sub(replace, path)
    return openapi_path, params


# ------------------------------------------------------------- operation


def _build_operation(
    route: Route,
    path_params: list[dict[str, Any]],
    schemas: dict[str, Any],
) -> dict[str, Any]:
    handler = _handler_of(route)
    signature = inspect.signature(handler) if handler else None
    hints = _type_hints_of(handler)

    operation: dict[str, Any] = {
        "operationId": _operation_id(route, handler),
        "summary": _summary_of(handler),
        "parameters": list(path_params),
        "responses": _build_responses(hints.get("return"), schemas),
    }
    full_doc = _description_of(handler)
    if full_doc:
        operation["description"] = full_doc

    # Request body: first DTO parameter on POST/PUT/PATCH.
    body_schema = _build_request_body(route, signature, hints, schemas)
    if body_schema is not None:
        operation["requestBody"] = body_schema

    tag = _tag_for(route)
    if tag:
        operation["tags"] = [tag]

    return operation


def _handler_of(route: Route) -> Any:
    action = route.action
    if isinstance(action, FunctionAction):
        return action.func
    if isinstance(action, ControllerAction):
        return getattr(action.controller_cls, action.method_name, None)
    return None


def _type_hints_of(handler: Any) -> dict[str, Any]:
    if handler is None:
        return {}
    try:
        import typing

        return typing.get_type_hints(handler)
    except Exception:
        return {}


def _operation_id(route: Route, handler: Any) -> str:
    if route.name:
        return route.name
    if handler is not None:
        return f"{handler.__module__}.{handler.__qualname__}".replace(".", "_")
    return f"{route.method.lower()}_{route.path}".replace("/", "_")


def _summary_of(handler: Any) -> str:
    if handler is None:
        return ""
    doc = inspect.getdoc(handler) or ""
    return doc.split("\n", 1)[0] if doc else ""


def _description_of(handler: Any) -> str:
    """Return the docstring body after the first-line summary.

    OpenAPI clients render ``description`` as Markdown — the body of a
    pylar docstring is already close enough to Markdown that passing
    it through verbatim produces a readable rendered page.
    """
    if handler is None:
        return ""
    doc = inspect.getdoc(handler) or ""
    if not doc or "\n" not in doc:
        return ""
    return doc.split("\n", 1)[1].strip()


def _tag_for(route: Route) -> str | None:
    action = route.action
    if isinstance(action, ControllerAction):
        # "PostController" → "Post"
        name = action.controller_cls.__name__
        return name[:-len("Controller")] if name.endswith("Controller") else name
    return None


# ------------------------------------------------------- request / responses


def _build_request_body(
    route: Route,
    signature: inspect.Signature | None,
    hints: dict[str, Any],
    schemas: dict[str, Any],
) -> dict[str, Any] | None:
    if route.method.upper() not in {"POST", "PUT", "PATCH"}:
        return None
    action = route.action
    dto_params = getattr(action, "dto_params", {}) or {}
    if not dto_params:
        return None
    # First DTO on the handler is the request body. Multiple DTOs are
    # allowed but OpenAPI only has one body slot — additional DTOs
    # fold into the same schema via anyOf downstream (phase 7c).
    dto_cls: type[BaseModel] = next(iter(dto_params.values()))
    ref = _register_schema(dto_cls, schemas)
    return {
        "required": True,
        "content": {
            "application/json": {"schema": {"$ref": ref}},
        },
    }


def _build_responses(
    return_annotation: Any,
    schemas: dict[str, Any],
) -> dict[str, Any]:
    success_schema = _schema_for_return(return_annotation, schemas)
    responses: dict[str, Any] = {
        "200": {
            "description": "Successful response",
        },
    }
    if success_schema is not None:
        responses["200"]["content"] = {
            "application/json": {"schema": success_schema},
        }
    # Standard error envelopes — see ADR-0007.
    responses["422"] = _error_response("Validation failed")
    responses["403"] = _error_response("Forbidden")
    return responses


def _schema_for_return(
    annotation: Any,
    schemas: dict[str, Any],
) -> dict[str, Any] | None:
    if annotation is None or annotation is inspect.Signature.empty:
        return None

    origin = get_origin(annotation)
    if origin is list:
        (inner,) = get_args(annotation) or (None,)
        if isinstance(inner, type) and issubclass(inner, BaseModel):
            return {
                "type": "array",
                "items": {"$ref": _register_schema(inner, schemas)},
            }
        return {"type": "array"}

    # Page[T] is a parameterised generic — treat `Page[PostResource]` as
    # the pagination envelope schema + the inner model schema.
    if isinstance(origin, type) and issubclass(origin, Page):
        (inner,) = get_args(annotation) or (None,)
        if isinstance(inner, type) and issubclass(inner, BaseModel):
            # Build a concrete Page[inner] subclass so pydantic can
            # render its JSON schema with the generic filled in.
            concrete = Page[inner]  # type: ignore[valid-type]
            return {"$ref": _register_schema(concrete, schemas)}

    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return {"$ref": _register_schema(annotation, schemas)}

    return None


def _register_schema(cls: type[BaseModel], schemas: dict[str, Any]) -> str:
    """Add *cls* to the components/schemas bag and return its ``$ref``."""
    name = _schema_name(cls)
    if name not in schemas:
        schema = cls.model_json_schema(
            ref_template="#/components/schemas/{model}"
        )
        # pydantic emits nested schemas under "$defs"; promote them to
        # components/schemas so the single global bag holds everything.
        for defname, defschema in (schema.pop("$defs", {}) or {}).items():
            schemas.setdefault(defname, defschema)
        schemas[name] = schema
    return f"#/components/schemas/{name}"


def _schema_name(cls: type[BaseModel]) -> str:
    # Generic ``Page[PostResource]`` renders as ``Page[PostResource]`` — we
    # normalise to an OpenAPI-friendly name.
    name = getattr(cls, "__name__", cls.__class__.__name__)
    return name.replace("[", "_").replace("]", "").replace(", ", "_")


def _error_response(description: str) -> dict[str, Any]:
    return {
        "description": description,
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "properties": {
                        "error": {
                            "type": "object",
                            "properties": {
                                "code": {"type": "string"},
                                "message": {"type": "string"},
                                "details": {"type": "array"},
                            },
                            "required": ["code", "message"],
                        },
                    },
                    "required": ["error"],
                }
            }
        },
    }
