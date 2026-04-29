"""Behavioural tests for :class:`pylar.routing.Router` and :class:`RouteGroup`."""

from __future__ import annotations

from pylar.http import Middleware, Request, RequestHandler, Response, json
from pylar.routing import Router


async def index(request: Request) -> Response:
    return json([])


async def show(request: Request) -> Response:
    return json({})


class _Auth:
    async def handle(self, request: Request, next_handler: RequestHandler) -> Response:
        return await next_handler(request)


class _Admin:
    async def handle(self, request: Request, next_handler: RequestHandler) -> Response:
        return await next_handler(request)


def _check_middleware_protocol() -> None:
    # Sanity check that our test middleware satisfy the Protocol — keeps the
    # type hints honest without forcing every test to do this.
    assert isinstance(_Auth(), Middleware)
    assert isinstance(_Admin(), Middleware)


def test_register_simple_get_route() -> None:
    router = Router()
    builder = router.get("/", index)

    # Fields are forwarded through the RouteBuilder proxy.
    assert builder.method == "GET"
    assert builder.path == "/"

    # The router's stored route reflects the registration.
    assert len(router.routes()) == 1
    stored = router.routes()[0]
    assert stored.method == "GET"
    assert stored.path == "/"
    assert stored is builder.route


def test_routes_preserve_registration_order() -> None:
    router = Router()
    router.get("/a", index)
    router.post("/b", show)
    router.put("/c", show)
    paths = [r.path for r in router.routes()]
    methods = [r.method for r in router.routes()]
    assert paths == ["/a", "/b", "/c"]
    assert methods == ["GET", "POST", "PUT"]


def test_route_middleware_is_attached_in_order() -> None:
    router = Router()
    router.get("/", index, middleware=[_Auth, _Admin])
    stored = router.routes()[0]
    assert stored.middleware == (_Auth, _Admin)


def test_named_route() -> None:
    router = Router()
    router.get("/users", index, name="users.index")
    stored = router.routes()[0]
    assert stored.name == "users.index"
    # Reverse lookup works because the registration recorded the index.
    assert router.url_for("users.index") == "/users"


def test_group_prefix_is_applied_to_child_routes() -> None:
    router = Router()
    admin = router.group(prefix="/admin")
    admin.get("/users", index)
    admin.post("/users", show)

    assert [r.path for r in router.routes()] == ["/admin/users", "/admin/users"]
    assert [r.method for r in router.routes()] == ["GET", "POST"]


def test_group_middleware_is_prepended_to_route_middleware() -> None:
    router = Router()
    admin = router.group(prefix="/admin", middleware=[_Auth])
    admin.get("/", index, middleware=[_Admin])

    route = router.routes()[0]
    assert route.middleware == (_Auth, _Admin)


def test_nested_groups_compose_prefix_and_middleware() -> None:
    router = Router()
    admin = router.group(prefix="/admin", middleware=[_Auth])
    admin_users = admin.group(prefix="/users", middleware=[_Admin])
    admin_users.get("/{id:int}", show)

    route = router.routes()[0]
    assert route.path == "/admin/users/{id:int}"
    assert route.middleware == (_Auth, _Admin)


def test_group_with_empty_prefix_does_not_add_slash() -> None:
    router = Router()
    g = router.group(middleware=[_Auth])
    g.get("/health", index)

    assert router.routes()[0].path == "/health"
    assert router.routes()[0].middleware == (_Auth,)


def test_group_path_joining_normalises_slashes() -> None:
    router = Router()
    g = router.group(prefix="/api/")
    g.get("/users", index)
    g.get("users/me", show)

    paths = [r.path for r in router.routes()]
    assert paths == ["/api/users", "/api/users/me"]
