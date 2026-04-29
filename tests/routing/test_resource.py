"""Tests for :meth:`Router.resource` and the resource controller convention."""

from __future__ import annotations

import pytest

from pylar.http import Request, RequestHandler, Response, json
from pylar.routing import Router
from pylar.routing.router import _singularize

# --------------------------------------------------------------------- helpers


class _Auth:
    async def handle(self, request: Request, next_handler: RequestHandler) -> Response:
        return await next_handler(request)


class FullController:
    async def index(self, request: Request) -> Response:
        return json([])

    async def store(self, request: Request) -> Response:
        return json({})

    async def show(self, request: Request) -> Response:
        return json({})

    async def update(self, request: Request) -> Response:
        return json({})

    async def destroy(self, request: Request) -> Response:
        return json({})


class ReadOnlyController:
    async def index(self, request: Request) -> Response:
        return json([])

    async def show(self, request: Request) -> Response:
        return json({})


# --------------------------------------------------------------- singulariser


@pytest.mark.parametrize("plural,singular", [
    ("posts", "post"),
    ("users", "user"),
    ("categories", "category"),
    ("classes", "class"),
    ("boxes", "box"),
    ("buses", "bus"),
    ("dishes", "dish"),
    ("watches", "watch"),
    ("class", "class"),  # ss does not get stripped
    ("ip", "ip"),         # no -s, leave alone
])
def test_singularise(plural: str, singular: str) -> None:
    assert _singularize(plural) == singular


# ------------------------------------------------------------- registrations


def test_full_resource_registers_five_routes() -> None:
    router = Router()
    router.resource("posts", FullController)

    routes = router.routes()
    assert len(routes) == 5

    by_method_path = {(r.method, r.path) for r in routes}
    assert by_method_path == {
        ("GET", "/posts"),
        ("POST", "/posts"),
        ("GET", "/posts/{post}"),
        ("PUT", "/posts/{post}"),
        ("DELETE", "/posts/{post}"),
    }


def test_resource_uses_action_named_routes() -> None:
    router = Router()
    router.resource("posts", FullController)
    assert router.url_for("posts.index") == "/posts"
    assert router.url_for("posts.show", {"post": 7}) == "/posts/7"
    assert router.url_for("posts.update", {"post": 7}) == "/posts/7"
    assert router.url_for("posts.destroy", {"post": 7}) == "/posts/7"


def test_read_only_controller_registers_only_existing_methods() -> None:
    router = Router()
    router.resource("articles", ReadOnlyController)

    routes = router.routes()
    methods = {(r.method, r.path) for r in routes}
    assert methods == {
        ("GET", "/articles"),
        ("GET", "/articles/{article}"),
    }


def test_only_keyword_keeps_listed_actions() -> None:
    router = Router()
    router.resource("posts", FullController, only=["index", "show"])
    methods = {r.method for r in router.routes()}
    assert methods == {"GET"}
    assert len(router.routes()) == 2


def test_except_keyword_drops_listed_actions() -> None:
    router = Router()
    router.resource("posts", FullController, except_=["destroy"])
    paths = {(r.method, r.path) for r in router.routes()}
    assert ("DELETE", "/posts/{post}") not in paths
    assert len(router.routes()) == 4


def test_parameter_override() -> None:
    router = Router()
    router.resource("posts", FullController, parameter="slug")
    show = next(r for r in router.routes() if r.method == "GET" and "{" in r.path)
    assert show.path == "/posts/{slug}"


def test_resource_middleware_attached_to_every_route() -> None:
    router = Router()
    router.resource("posts", FullController, middleware=[_Auth])
    for route in router.routes():
        assert route.middleware == (_Auth,)


def test_resource_inside_group_inherits_prefix_and_middleware() -> None:
    router = Router()
    api = router.group(prefix="/api/v1", middleware=[_Auth])
    api.resource("posts", FullController)

    paths = [r.path for r in router.routes()]
    assert all(path.startswith("/api/v1/posts") for path in paths)
    for route in router.routes():
        assert _Auth in route.middleware
