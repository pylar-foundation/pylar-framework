"""The :class:`Router`, :class:`RouteGroup`, and :class:`RouteBuilder`."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import replace

from pylar.http.middleware import Middleware
from pylar.routing.action import Action, Handler
from pylar.routing.exceptions import RoutingError
from pylar.routing.route import Route
from pylar.routing.websocket import WebSocketHandler, WebSocketRouteSpec

#: Captures ``{name}`` and ``{name:converter}`` placeholders in a path
#: pattern. Used by :meth:`Router.url_for` to substitute named-route
#: arguments back into the registered pattern.
_PATH_PARAM_RE = re.compile(r"\{([^:}]+)(?::[^}]+)?\}")


class Router:
    """The root collection of routes for an application.

    Routes are appended in registration order. The :class:`HttpKernel` reads
    them via :meth:`routes` at the moment it builds the underlying Starlette
    app, so providers may register routes at any time during their boot phase.

    Verb methods (``get``, ``post``, ...) return a :class:`RouteBuilder`
    that supports both the existing keyword-argument style and a fluent
    chain (`router.get(...).middleware(Auth).name("home")`). Either form
    produces the same registered :class:`Route`.
    """

    def __init__(self) -> None:
        self._routes: list[Route] = []
        self._websocket_routes: list[WebSocketRouteSpec] = []
        self._named: dict[str, int] = {}
        self._fallback: Handler | None = None

    # ----------------------------------------------------------------- HTTP verbs

    def get(
        self,
        path: str,
        handler: Handler,
        *,
        middleware: Sequence[type[Middleware]] = (),
        name: str | None = None,
    ) -> RouteBuilder:
        return self._add("GET", path, handler, middleware=middleware, name=name)

    def post(
        self,
        path: str,
        handler: Handler,
        *,
        middleware: Sequence[type[Middleware]] = (),
        name: str | None = None,
    ) -> RouteBuilder:
        return self._add("POST", path, handler, middleware=middleware, name=name)

    def put(
        self,
        path: str,
        handler: Handler,
        *,
        middleware: Sequence[type[Middleware]] = (),
        name: str | None = None,
    ) -> RouteBuilder:
        return self._add("PUT", path, handler, middleware=middleware, name=name)

    def patch(
        self,
        path: str,
        handler: Handler,
        *,
        middleware: Sequence[type[Middleware]] = (),
        name: str | None = None,
    ) -> RouteBuilder:
        return self._add("PATCH", path, handler, middleware=middleware, name=name)

    def delete(
        self,
        path: str,
        handler: Handler,
        *,
        middleware: Sequence[type[Middleware]] = (),
        name: str | None = None,
    ) -> RouteBuilder:
        return self._add("DELETE", path, handler, middleware=middleware, name=name)

    def options(
        self,
        path: str,
        handler: Handler,
        *,
        middleware: Sequence[type[Middleware]] = (),
        name: str | None = None,
    ) -> RouteBuilder:
        return self._add("OPTIONS", path, handler, middleware=middleware, name=name)

    # ---------------------------------------------------------------------- group

    def group(
        self,
        *,
        prefix: str = "",
        middleware: Sequence[type[Middleware]] = (),
    ) -> RouteGroup:
        """Open a group whose registrations inherit *prefix* and *middleware*."""
        return RouteGroup(router=self, prefix=prefix, middleware=tuple(middleware))

    # -------------------------------------------------------------- websocket

    def websocket(
        self,
        path: str,
        handler: WebSocketHandler,
        *,
        name: str | None = None,
    ) -> WebSocketRouteSpec:
        """Register a WebSocket endpoint at *path*."""
        spec = WebSocketRouteSpec(path=path, handler=handler, name=name)
        self._websocket_routes.append(spec)
        return spec

    # ------------------------------------------------------------------ resource

    def resource(
        self,
        path: str,
        controller: type,
        *,
        only: Sequence[str] | None = None,
        except_: Sequence[str] | None = None,
        parameter: str | None = None,
        middleware: Sequence[type[Middleware]] = (),
    ) -> tuple[RouteBuilder, ...]:
        """Register the standard REST resource for *controller*.

        Generates up to five routes pointing at the matching method on
        *controller*::

            GET    /<path>             → controller.index    name=<path>.index
            POST   /<path>             → controller.store    name=<path>.store
            GET    /<path>/{param}     → controller.show     name=<path>.show
            PUT    /<path>/{param}     → controller.update   name=<path>.update
            DELETE /<path>/{param}     → controller.destroy  name=<path>.destroy

        Methods that the controller does not implement are silently
        skipped, so a read-only resource simply omits ``store`` /
        ``update`` / ``destroy``. ``only`` and ``except_`` give the user
        explicit control: ``only=["index", "show"]`` keeps just those
        two; ``except_=["destroy"]`` keeps everything else.

        ``parameter`` is the name of the path placeholder for the
        single-row routes. It defaults to the singular form of the
        resource path (``posts`` → ``post``) so that the standard
        Django-style model binding kicks in automatically.
        """
        cleaned = path.strip("/")
        param_name = parameter or _singularize(cleaned)
        prefix = f"/{cleaned}"
        item_path = f"{prefix}/{{{param_name}}}"

        all_actions: tuple[tuple[str, str, str], ...] = (
            ("index", "GET", prefix),
            ("store", "POST", prefix),
            ("show", "GET", item_path),
            ("update", "PUT", item_path),
            ("destroy", "DELETE", item_path),
        )

        selected: set[str] = {action_name for action_name, _, _ in all_actions}
        if only is not None:
            selected = set(only)
        if except_ is not None:
            selected -= set(except_)

        builders: list[RouteBuilder] = []
        for action_name, verb, route_path in all_actions:
            if action_name not in selected:
                continue
            handler = getattr(controller, action_name, None)
            if handler is None:
                continue
            builder = self._add(
                verb,
                route_path,
                handler,
                middleware=middleware,
                name=f"{cleaned}.{action_name}",
            )
            builders.append(builder)
        return tuple(builders)

    # ---------------------------------------------------------------- url_for

    def url_for(
        self,
        name: str,
        params: dict[str, object] | None = None,
    ) -> str:
        """Render the path of the named route, substituting *params*.

        Raises :class:`RoutingError` when the name is unknown, when a
        required placeholder is missing from *params*, or when *params*
        contains keys that are not part of the route pattern. The
        result is a URL path (no scheme, no host) — suitable for
        redirects and templates.
        """
        if name not in self._named:
            raise RoutingError(f"No route named {name!r}")
        route = self._routes[self._named[name]]
        return _substitute_path(route.path, params or {}, name)

    # ---------------------------------------------------------------------- query

    def fallback(self, handler: Handler) -> None:
        """Register a catch-all handler for unmatched requests.

        Matches Laravel's ``Route::fallback()`` — the handler receives
        any request that doesn't match a registered route, typically
        to render a custom 404 page. Only one fallback is allowed;
        later calls overwrite earlier ones.
        """
        self._fallback = handler

    @property
    def fallback_handler(self) -> Handler | None:
        return self._fallback

    def routes(self) -> tuple[Route, ...]:
        """Return all HTTP routes registered so far, in declaration order."""
        return tuple(self._routes)

    def websocket_routes(self) -> tuple[WebSocketRouteSpec, ...]:
        """Return all WebSocket routes registered so far, in declaration order."""
        return tuple(self._websocket_routes)

    def named_routes(self) -> tuple[str, ...]:
        """Return the sorted tuple of every registered route name."""
        return tuple(sorted(self._named))

    # ------------------------------------------------------------------ internals

    def _add(
        self,
        method: str,
        path: str,
        handler: Handler,
        *,
        middleware: Sequence[type[Middleware]],
        name: str | None,
    ) -> RouteBuilder:
        route = Route(
            method=method,
            path=path,
            action=Action.from_handler(handler),
            middleware=tuple(middleware),
            name=name,
        )
        self._routes.append(route)
        index = len(self._routes) - 1
        if name is not None:
            self._named[name] = index
        return RouteBuilder(self, index)


class RouteBuilder:
    """Fluent proxy returned from every :class:`Router` verb method.

    Supports the chain ``router.get(path, handler).middleware(Auth).name("home")``
    while still exposing every :class:`Route` field via attribute
    forwarding so older test code that did ``router.get(...).method``
    keeps working without changes.
    """

    __slots__ = ("_index", "_router")

    def __init__(self, router: Router, index: int) -> None:
        self._router = router
        self._index = index

    @property
    def route(self) -> Route:
        """The currently-stored :class:`Route` for this builder."""
        return self._router._routes[self._index]

    def middleware(self, *classes: type[Middleware]) -> RouteBuilder:
        """Append *classes* to this route's middleware pipeline."""
        current = self.route
        updated = replace(
            current, middleware=(*current.middleware, *classes)
        )
        self._router._routes[self._index] = updated
        return self

    def name(self, name: str) -> RouteBuilder:
        """Attach a stable name so the route can be looked up via :meth:`Router.url_for`."""
        current = self.route
        updated = replace(current, name=name)
        self._router._routes[self._index] = updated
        self._router._named[name] = self._index
        return self

    def cache(self, seconds: int = 60) -> RouteBuilder:
        """Add HTTP response caching for *seconds*.

        Creates an inline subclass of :class:`CacheResponseMiddleware`
        with the requested TTL and appends it to the route's middleware
        pipeline::

            router.get("/posts", PostController.index).cache(seconds=120)
        """
        from pylar.routing.cache import CacheResponseMiddleware

        # Create a subclass with the caller's TTL so that each .cache()
        # call can have a different duration without shared state.
        cached_cls: type[CacheResponseMiddleware] = type(
            f"CacheResponse_{seconds}s",
            (CacheResponseMiddleware,),
            {"seconds": seconds},
        )
        return self.middleware(cached_cls)

    # ------------------------------------------------------- forwarding

    def __getattr__(self, item: str) -> object:
        # Anything not implemented above is fetched off the underlying
        # Route, so existing code that wrote ``builder.method`` /
        # ``builder.path`` keeps working without ceremony.
        return getattr(self.route, item)

    def __repr__(self) -> str:
        return f"<RouteBuilder {self.route!r}>"


class RouteGroup:
    """A scoped builder that prepends a prefix and stacks middleware on every route."""

    def __init__(
        self,
        router: Router,
        *,
        prefix: str,
        middleware: tuple[type[Middleware], ...],
    ) -> None:
        self._router = router
        self._prefix = prefix
        self._middleware = middleware

    # The verb methods mirror Router's, but combine prefix + middleware before
    # delegating. They are intentionally not factored through __getattr__ —
    # explicit methods keep the public surface fully typed.

    def get(
        self,
        path: str,
        handler: Handler,
        *,
        middleware: Sequence[type[Middleware]] = (),
        name: str | None = None,
    ) -> RouteBuilder:
        return self._router._add(
            "GET",
            self._combine_path(path),
            handler,
            middleware=self._combine_middleware(middleware),
            name=name,
        )

    def post(
        self,
        path: str,
        handler: Handler,
        *,
        middleware: Sequence[type[Middleware]] = (),
        name: str | None = None,
    ) -> RouteBuilder:
        return self._router._add(
            "POST",
            self._combine_path(path),
            handler,
            middleware=self._combine_middleware(middleware),
            name=name,
        )

    def put(
        self,
        path: str,
        handler: Handler,
        *,
        middleware: Sequence[type[Middleware]] = (),
        name: str | None = None,
    ) -> RouteBuilder:
        return self._router._add(
            "PUT",
            self._combine_path(path),
            handler,
            middleware=self._combine_middleware(middleware),
            name=name,
        )

    def patch(
        self,
        path: str,
        handler: Handler,
        *,
        middleware: Sequence[type[Middleware]] = (),
        name: str | None = None,
    ) -> RouteBuilder:
        return self._router._add(
            "PATCH",
            self._combine_path(path),
            handler,
            middleware=self._combine_middleware(middleware),
            name=name,
        )

    def delete(
        self,
        path: str,
        handler: Handler,
        *,
        middleware: Sequence[type[Middleware]] = (),
        name: str | None = None,
    ) -> RouteBuilder:
        return self._router._add(
            "DELETE",
            self._combine_path(path),
            handler,
            middleware=self._combine_middleware(middleware),
            name=name,
        )

    def options(
        self,
        path: str,
        handler: Handler,
        *,
        middleware: Sequence[type[Middleware]] = (),
        name: str | None = None,
    ) -> RouteBuilder:
        return self._router._add(
            "OPTIONS",
            self._combine_path(path),
            handler,
            middleware=self._combine_middleware(middleware),
            name=name,
        )

    def resource(
        self,
        path: str,
        controller: type,
        *,
        only: Sequence[str] | None = None,
        except_: Sequence[str] | None = None,
        parameter: str | None = None,
        middleware: Sequence[type[Middleware]] = (),
    ) -> tuple[RouteBuilder, ...]:
        """Register a REST resource scoped to this group's prefix and middleware."""
        return self._router.resource(
            self._combine_path(path).lstrip("/"),
            controller,
            only=only,
            except_=except_,
            parameter=parameter,
            middleware=self._combine_middleware(middleware),
        )

    def group(
        self,
        *,
        prefix: str = "",
        middleware: Sequence[type[Middleware]] = (),
    ) -> RouteGroup:
        """Open a nested group — prefixes concatenate, middleware accumulates."""
        return RouteGroup(
            router=self._router,
            prefix=self._combine_path(prefix),
            middleware=self._combine_middleware(middleware),
        )

    # ------------------------------------------------------------------ internals

    def _combine_path(self, path: str) -> str:
        if not path:
            return self._prefix
        if not self._prefix:
            return path
        return self._prefix.rstrip("/") + "/" + path.lstrip("/")

    def _combine_middleware(
        self, extra: Sequence[type[Middleware]]
    ) -> tuple[type[Middleware], ...]:
        return (*self._middleware, *extra)


# ----------------------------------------------------------------- helpers


def _singularize(name: str) -> str:
    """Trivial English singulariser used by :meth:`Router.resource`.

    Handles the common ``-ies`` / ``-ses`` / ``-xes`` / ``-s`` cases.
    Anything more sophisticated is the user's job — pass ``parameter=``
    explicitly when the auto-derived name is wrong.
    """
    if name.endswith("ies") and len(name) > 3:
        return name[:-3] + "y"
    if name.endswith(("ses", "xes", "zes", "ches", "shes")):
        return name[:-2]
    if name.endswith("s") and not name.endswith("ss"):
        return name[:-1]
    return name


def _substitute_path(
    pattern: str,
    params: dict[str, object],
    route_name: str,
) -> str:
    """Replace ``{name}`` placeholders in *pattern* with the matching *params*.

    Raises :class:`RoutingError` for missing or unused parameters so the
    caller learns about typos at the call site instead of from a 404
    later in the test cycle.
    """
    used: set[str] = set()

    def replace(match: re.Match[str]) -> str:
        param_name = match.group(1)
        used.add(param_name)
        if param_name not in params:
            raise RoutingError(
                f"Missing parameter {param_name!r} for route {route_name!r}"
            )
        return str(params[param_name])

    rendered = _PATH_PARAM_RE.sub(replace, pattern)

    extras = set(params) - used
    if extras:
        raise RoutingError(
            f"Unused parameters {sorted(extras)} for route {route_name!r}"
        )

    return rendered
