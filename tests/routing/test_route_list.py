"""Tests for the route:list command."""

from __future__ import annotations

from pylar.console.output import BufferedOutput
from pylar.http import Request, Response, json
from pylar.routing.commands import RouteListCommand, RouteListInput
from pylar.routing.router import Router


async def _dummy(request: Request) -> Response:
    return json({})


class DummyController:
    async def index(self, request: Request) -> Response:
        return json({})

    async def show(self, request: Request, pk: int) -> Response:
        return json({})


def _build_router() -> Router:
    router = Router()
    router.get("/", _dummy, name="home")
    router.get("/api/posts", DummyController.index, name="posts.index")
    router.post("/api/posts", DummyController.index, name="posts.store")
    router.get("/api/posts/{pk:int}", DummyController.show, name="posts.show")
    router.delete("/api/posts/{pk:int}", DummyController.show, name="posts.destroy")
    return router


class TestRouteListCommand:
    async def test_lists_all_routes(self) -> None:
        out = BufferedOutput()
        cmd = RouteListCommand(_build_router(), out)
        code = await cmd.handle(RouteListInput())
        output = out.getvalue()
        assert code == 0
        assert "GET" in output
        assert "POST" in output
        assert "DELETE" in output
        assert "/api/posts" in output
        assert "posts.index" in output
        assert "5 route(s)" in output

    async def test_filter_by_method(self) -> None:
        out = BufferedOutput()
        cmd = RouteListCommand(_build_router(), out)
        code = await cmd.handle(RouteListInput(method="GET"))
        output = out.getvalue()
        assert code == 0
        assert "POST" not in output
        assert "DELETE" not in output
        assert "3 route(s)" in output

    async def test_filter_by_name(self) -> None:
        out = BufferedOutput()
        cmd = RouteListCommand(_build_router(), out)
        code = await cmd.handle(RouteListInput(name="posts"))
        output = out.getvalue()
        assert code == 0
        assert "home" not in output
        assert "4 route(s)" in output

    async def test_filter_by_path(self) -> None:
        out = BufferedOutput()
        cmd = RouteListCommand(_build_router(), out)
        code = await cmd.handle(RouteListInput(path="/api"))
        output = out.getvalue()
        assert code == 0
        assert "4 route(s)" in output

    async def test_empty_router(self) -> None:
        out = BufferedOutput()
        cmd = RouteListCommand(Router(), out)
        code = await cmd.handle(RouteListInput())
        assert code == 0
        assert "No routes registered" in out.getvalue()

    async def test_no_match(self) -> None:
        out = BufferedOutput()
        cmd = RouteListCommand(_build_router(), out)
        code = await cmd.handle(RouteListInput(method="PATCH"))
        assert code == 0
        assert "No routes match" in out.getvalue()

    async def test_sort_by_method(self) -> None:
        out = BufferedOutput()
        cmd = RouteListCommand(_build_router(), out)
        code = await cmd.handle(RouteListInput(sort="method"))
        assert code == 0
        # DELETE should appear before GET alphabetically.
        output = out.getvalue()
        assert "DELETE" in output

    async def test_controller_action_label(self) -> None:
        out = BufferedOutput()
        cmd = RouteListCommand(_build_router(), out)
        await cmd.handle(RouteListInput())
        output = out.getvalue()
        # Rich may truncate long column values, so check prefix.
        assert "DummyController.i" in output  # .index (may be truncated)
        assert "DummyController.s" in output  # .show (may be truncated)
