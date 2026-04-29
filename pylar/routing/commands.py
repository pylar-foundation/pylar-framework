"""Console commands for the routing layer."""

from __future__ import annotations

from dataclasses import dataclass

from pylar.console.command import Command
from pylar.console.output import Output
from pylar.routing.action import ControllerAction, FunctionAction
from pylar.routing.router import Router


@dataclass(frozen=True)
class RouteListInput:
    """Options for the route:list command.

    --method    Filter routes by HTTP method (GET, POST, etc.)
    --name      Filter routes whose name contains this substring
    --path      Filter routes whose path contains this substring
    --sort      Sort by: method, path, name, action (default: path)
    --reverse   Reverse sort order
    """

    method: str = ""
    name: str = ""
    path: str = ""
    sort: str = "path"
    reverse: bool = False


class RouteListCommand(Command[RouteListInput]):
    """Display all registered routes in a formatted table."""

    name = "route:list"
    description = "List all registered routes"
    input_type = RouteListInput

    def __init__(self, router: Router, output: Output) -> None:
        self._router = router
        self._out = output

    async def handle(self, input: RouteListInput) -> int:
        routes = list(self._router.routes())
        ws_routes = list(self._router.websocket_routes())

        if not routes and not ws_routes:
            self._out.info("No routes registered.")
            return 0

        # Build row data for HTTP routes.
        rows: list[tuple[str, str, str, str, str]] = []
        for route in routes:
            method_str = route.method
            path = route.path
            route_name = route.name or ""
            action_label = _action_label(route.action)
            middleware_label = _middleware_label(route.middleware)

            if input.method and method_str.upper() != input.method.upper():
                continue
            if input.name and input.name not in route_name:
                continue
            if input.path and input.path not in path:
                continue

            # Colour the method.
            method_coloured = _colour_method(method_str)
            rows.append((method_coloured, path, route_name, action_label, middleware_label))

        # Add WebSocket routes.
        for ws in ws_routes:
            path = ws.path
            route_name = ws.name or ""
            handler = ws.handler
            action_label = getattr(handler, "__qualname__", repr(handler))
            middleware_label = ""

            if input.method and "WS" != input.method.upper():
                continue
            if input.name and input.name not in route_name:
                continue
            if input.path and input.path not in path:
                continue

            rows.append(("[magenta]WS[/magenta]", path, route_name, action_label, middleware_label))

        if not rows:
            self._out.info("No routes match the given filters.")
            return 0

        # Sort (use plain text for sorting, not ANSI).
        sort_keys = {"method": 0, "path": 1, "name": 2, "action": 3}
        sort_idx = sort_keys.get(input.sort, 1)
        rows.sort(key=lambda r: r[sort_idx], reverse=input.reverse)

        self._out.table(
            headers=("Method", "URI", "Name", "Action", "Middleware"),
            rows=rows,
            title="Registered Routes",
        )

        self._out.newline()
        self._out.info(f"Showing {len(rows)} route(s)")
        return 0


def _colour_method(method: str) -> str:
    """Apply Rich colour markup to HTTP method."""
    colours: dict[str, str] = {
        "GET": "green",
        "POST": "yellow",
        "PUT": "blue",
        "PATCH": "cyan",
        "DELETE": "red",
        "OPTIONS": "dim",
        "HEAD": "dim",
    }
    colour = colours.get(method, "white")
    return f"[{colour}]{method}[/{colour}]"


def _action_label(action: object) -> str:
    """Build a human-readable label for an action."""
    if isinstance(action, ControllerAction):
        return f"{action.controller_cls.__name__}.{action.method_name}"
    if isinstance(action, FunctionAction):
        func = action.func
        qualname = getattr(func, "__qualname__", "")
        if "<locals>" in qualname:
            module = getattr(func, "__module__", "")
            name = getattr(func, "__name__", repr(func))
            return f"{module}.{name}" if module else name
        return qualname
    return repr(action)


def _middleware_label(middleware: tuple[type, ...]) -> str:
    """Build a comma-separated list of middleware class names."""
    if not middleware:
        return ""
    return ", ".join(cls.__name__ for cls in middleware)
