"""Translate :class:`pylar.routing.Route` objects into Starlette routes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.routing import BaseRoute
from starlette.routing import Route as StarletteRoute
from starlette.routing import WebSocketRoute as StarletteWebSocketRoute
from starlette.websockets import WebSocket

from pylar.auth.exceptions import AuthorizationError
from pylar.foundation.container import Container
from pylar.http.middleware import Middleware, Pipeline
from pylar.http.request import Request
from pylar.http.response import JsonResponse, Response
from pylar.routing.route import Route
from pylar.routing.router import Router
from pylar.routing.websocket import WebSocketRouteSpec
from pylar.validation.exceptions import ValidationError
from pylar.validation.renderer import DefaultValidationRenderer, ValidationErrorRenderer

#: Internal type alias — Starlette endpoints are async callables that take a
#: Starlette request and return a Starlette response. We satisfy that contract
#: by treating ``Request`` / ``Response`` as the same types (we re-export them
#: directly from Starlette).
StarletteEndpoint = Callable[[Request], Awaitable[Response]]


class RoutesCompiler:
    """Build Starlette routes from a populated :class:`Router`."""

    def __init__(self, container: Container) -> None:
        self._container = container

    def compile(self, router: Router) -> list[BaseRoute]:
        compiled: list[BaseRoute] = [self._compile_route(r) for r in router.routes()]
        compiled.extend(self._auto_options(router))
        compiled.extend(self._compile_websocket(spec) for spec in router.websocket_routes())
        # Catch-all fallback (Route::fallback equivalent).
        if router.fallback_handler is not None:
            from pylar.routing.action import Action

            fallback_action = Action.from_handler(router.fallback_handler)
            container = self._container

            async def fallback_endpoint(request: Request) -> Response:
                return await fallback_action.invoke(
                    container, request, dict(request.path_params)
                )

            compiled.append(
                StarletteRoute("/{path:path}", endpoint=fallback_endpoint)
            )
        return compiled

    def _auto_options(self, router: Router) -> list[BaseRoute]:
        """Generate a 204 OPTIONS handler for paths that lack one."""
        paths_with_options: set[str] = set()
        paths_seen: dict[str, list[str]] = {}
        for route in router.routes():
            paths_seen.setdefault(route.path, []).append(route.method)
            if route.method.upper() == "OPTIONS":
                paths_with_options.add(route.path)

        result: list[BaseRoute] = []
        for path, methods in paths_seen.items():
            if path in paths_with_options:
                continue
            allowed = ", ".join(sorted(set(m.upper() for m in methods) | {"OPTIONS"}))

            async def _options_handler(
                request: Request, _allowed: str = allowed
            ) -> Response:
                return Response(
                    status_code=204,
                    headers={"Allow": _allowed},
                )

            result.append(
                StarletteRoute(
                    path=path,
                    endpoint=_options_handler,
                    methods=["OPTIONS"],
                )
            )
        return result

    # ------------------------------------------------------------------ internals

    def _compile_route(self, route: Route) -> BaseRoute:
        endpoint = self._make_endpoint(route)
        return StarletteRoute(
            path=route.path,
            endpoint=endpoint,
            methods=[route.method],
            name=route.name,
        )

    def _compile_websocket(self, spec: WebSocketRouteSpec) -> BaseRoute:
        endpoint = self._make_websocket_endpoint(spec)
        return StarletteWebSocketRoute(path=spec.path, endpoint=endpoint, name=spec.name)

    def _make_websocket_endpoint(
        self, spec: WebSocketRouteSpec
    ) -> Callable[[WebSocket], Awaitable[None]]:
        container = self._container
        handler = spec.handler

        async def endpoint(websocket: WebSocket) -> None:
            result = container.call(
                handler,
                overrides={WebSocket: websocket},
                params=dict(websocket.path_params),
            )
            await result

        return endpoint

    def _make_endpoint(self, route: Route) -> StarletteEndpoint:
        container = self._container
        action = route.action
        middleware_classes = route.middleware
        # Pre-build middleware whose constructor has no parameters
        # (stateless) so we don't allocate a new instance per request.
        cached_middlewares: list[Middleware | None] = []
        for cls in middleware_classes:
            try:
                import inspect

                sig = inspect.signature(cls.__init__) if hasattr(cls, "__init__") else None
                params = [
                    p for p in (sig.parameters.values() if sig else [])
                    if p.name != "self"
                ]
                if not params:
                    cached_middlewares.append(cls())
                else:
                    cached_middlewares.append(None)
            except (TypeError, ValueError):
                cached_middlewares.append(None)

        async def endpoint(request: Request) -> Response:
            with container.scope():
                middlewares: list[Middleware] = [
                    cached or container.make(cls)
                    for cached, cls in zip(
                        cached_middlewares,
                        middleware_classes,
                        strict=True,
                    )
                ]
                pipeline = Pipeline(middlewares)

                async def finalizer(req: Request) -> Response:
                    return await action.invoke(container, req, dict(req.path_params))

                try:
                    return await pipeline.send(request, finalizer)
                except ValidationError as exc:
                    try:
                        renderer = container.make(ValidationErrorRenderer)  # type: ignore[type-abstract]
                    except Exception:
                        renderer = DefaultValidationRenderer()
                    return renderer.render(exc.errors)
                except AuthorizationError as exc:
                    return JsonResponse(
                        content={"error": exc.detail, "ability": exc.ability},
                        status_code=403,
                    )

        return endpoint
