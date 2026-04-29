"""Tests for the fluent :class:`RouteBuilder` and :meth:`Router.url_for`."""

from __future__ import annotations

import pytest

from pylar.http import Request, RequestHandler, Response, json
from pylar.routing import Router, RoutingError


async def index(request: Request) -> Response:
    return json([])


async def show(request: Request) -> Response:
    return json({})


class _Auth:
    async def handle(self, request: Request, next_handler: RequestHandler) -> Response:
        return await next_handler(request)


class _Throttle:
    async def handle(self, request: Request, next_handler: RequestHandler) -> Response:
        return await next_handler(request)


def test_fluent_middleware_chain_appends() -> None:
    router = Router()
    router.get("/", index).middleware(_Auth).middleware(_Throttle)
    stored = router.routes()[0]
    assert stored.middleware == (_Auth, _Throttle)


def test_fluent_middleware_accepts_multiple_classes() -> None:
    router = Router()
    router.get("/", index).middleware(_Auth, _Throttle)
    stored = router.routes()[0]
    assert stored.middleware == (_Auth, _Throttle)


def test_fluent_middleware_combines_with_keyword_argument() -> None:
    router = Router()
    router.get("/", index, middleware=[_Auth]).middleware(_Throttle)
    stored = router.routes()[0]
    assert stored.middleware == (_Auth, _Throttle)


def test_fluent_name_registers_for_url_for() -> None:
    router = Router()
    router.get("/", index).name("home")
    assert router.url_for("home") == "/"


def test_fluent_chain_returns_self_for_full_chain() -> None:
    router = Router()
    builder = router.get("/", index).middleware(_Auth).name("home")
    # Final builder still references the same underlying route.
    assert builder.route.middleware == (_Auth,)
    assert builder.route.name == "home"


# ----------------------------------------------------------------- url_for


def test_url_for_renders_typed_path_params() -> None:
    router = Router()
    router.get("/posts/{post_id:int}", show, name="posts.show")
    assert router.url_for("posts.show", {"post_id": 42}) == "/posts/42"


def test_url_for_renders_string_path_params() -> None:
    router = Router()
    router.get("/users/{handle}", show, name="users.show")
    assert router.url_for("users.show", {"handle": "alice"}) == "/users/alice"


def test_url_for_handles_multiple_placeholders() -> None:
    router = Router()
    router.get(
        "/orgs/{org}/users/{user_id:int}",
        show,
        name="orgs.users.show",
    )
    rendered = router.url_for(
        "orgs.users.show", {"org": "acme", "user_id": 7}
    )
    assert rendered == "/orgs/acme/users/7"


def test_url_for_unknown_name_raises() -> None:
    router = Router()
    with pytest.raises(RoutingError, match="No route named"):
        router.url_for("nope")


def test_url_for_missing_param_raises() -> None:
    router = Router()
    router.get("/posts/{post_id:int}", show, name="posts.show")
    with pytest.raises(RoutingError, match="Missing parameter"):
        router.url_for("posts.show")


def test_url_for_extra_param_raises() -> None:
    router = Router()
    router.get("/posts", index, name="posts.index")
    with pytest.raises(RoutingError, match="Unused parameters"):
        router.url_for("posts.index", {"unexpected": 1})


def test_named_routes_returns_sorted_tuple() -> None:
    router = Router()
    router.get("/", index, name="home")
    router.get("/about", show, name="about")
    router.get("/contact", show).name("contact")
    assert router.named_routes() == ("about", "contact", "home")
