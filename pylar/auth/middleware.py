"""HTTP middleware that runs the configured :class:`Guard` per request."""

from __future__ import annotations

from pylar.auth.context import authenticate_as, current_user_or_none
from pylar.auth.contracts import Guard
from pylar.auth.gate import Gate
from pylar.http.exceptions import Unauthorized
from pylar.http.middleware import RequestHandler
from pylar.http.request import Request
from pylar.http.response import Response
from pylar.routing.throttle import ThrottleMiddleware


class LoginThrottleMiddleware(ThrottleMiddleware):
    """Aggressive rate-limit for authentication endpoints.

    Defaults to **5 requests per 60 seconds** per IP — tight enough to
    deter credential-stuffing while still comfortable for a human who
    fat-fingers a password. Attach it to your login / register /
    password-reset routes::

        auth_routes = router.group(middleware=[LoginThrottleMiddleware])
        auth_routes.post("/login", AuthController.login)
        auth_routes.post("/register", AuthController.register)

    The middleware inherits all behaviour from
    :class:`~pylar.routing.ThrottleMiddleware`: cache-backed atomic
    counters, ``Retry-After`` headers on 429, and the ability to
    override :meth:`identity_for` if you need composite keys.
    """

    max_requests: int = 5
    window_seconds: int = 60
    key_prefix: str = "throttle:login"


class AuthMiddleware:
    """Resolve the current user via the bound :class:`Guard` and install it.

    The middleware is a thin wrapper: it asks the guard "who is this?",
    binds the answer (or ``None``) to the :func:`current_user` context, and
    delegates to the next handler. It does **not** reject unauthenticated
    requests on its own — that decision belongs to per-route policies and
    gates, which can distinguish "no user" from "wrong user" in a way the
    middleware cannot.
    """

    def __init__(self, guard: Guard) -> None:
        self._guard = guard

    async def handle(self, request: Request, next_handler: RequestHandler) -> Response:
        user = await self._guard.authenticate(request)
        with authenticate_as(user):
            return await next_handler(request)


class AuthorizeMiddleware:
    """Run a :class:`Gate` authorization check before the handler executes.

    Create via the :func:`authorize` factory and attach to a route::

        router.put(
            "/posts/{post}",
            PostController.update,
            middleware=[authorize("update")],
        )

    The middleware reads :func:`current_user`, asks the gate
    ``gate.authorize(user, ability)`` (no target), and raises 403 on
    failure. For model-level checks, pass ``gate.authorize()`` inside
    the controller — the middleware handles the common "user must be
    authenticated and have this ability" case.

    For standalone abilities (not policy-bound)::

        middleware=[authorize("access-admin")]
    """

    ability: str

    def __init__(self, gate: Gate) -> None:
        self._gate = gate

    async def handle(self, request: Request, next_handler: RequestHandler) -> Response:
        from pylar.auth.context import current_user

        user = current_user()
        await self._gate.authorize(user, self.ability)
        return await next_handler(request)


def authorize(ability: str) -> type[AuthorizeMiddleware]:
    """Create a middleware class that checks *ability* via the Gate.

    Returns a new subclass of :class:`AuthorizeMiddleware` with the
    requested ability baked in. The Gate is injected by the container
    at request time::

        router.get("/admin", DashboardController.index, middleware=[
            AuthMiddleware,
            RequireAuthMiddleware,
            authorize("access-admin"),
        ])
    """
    return type(
        f"Authorize_{ability}",
        (AuthorizeMiddleware,),
        {"ability": ability},
    )


class RequireAuthMiddleware:
    """Reject anonymous requests with a 401 before they reach the controller.

    Place this *after* :class:`AuthMiddleware` on routes that require an
    authenticated user::

        api = router.group(middleware=[AuthMiddleware, RequireAuthMiddleware])
        api.get("/me", UserController.show)

    The middleware reads :func:`current_user_or_none` (which AuthMiddleware
    populates from the bound guard) and raises
    :class:`pylar.http.Unauthorized` when the slot is empty. The route
    compiler turns the ``HTTPException`` into a 401 response with no
    extra wiring on the controller side.

    Routes that need to distinguish "no user → public, draft hidden"
    from "anonymous → forbidden" should *not* use this middleware and
    instead read ``current_user_or_none`` themselves.
    """

    async def handle(self, request: Request, next_handler: RequestHandler) -> Response:
        if current_user_or_none() is None:
            raise Unauthorized()
        return await next_handler(request)
