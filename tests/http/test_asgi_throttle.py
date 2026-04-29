"""Verify the global ASGI throttle renders formatted 429 responses.

The middleware short-circuits before any route matching, so if it
ever reverts to the raw ``"Too Many Requests"`` plaintext body the
whole framework-wide HTML error-page contract breaks (a browser
client would land on a bare text/plain page on any throttled
request). These tests pin the contract:

* JSON clients get ``{"message": "Too Many Requests", "code": 429}``.
* HTML clients get the framework's built-in styled 429 page with
  the ``Retry-After`` header populated.
"""

from __future__ import annotations

import httpx
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from pylar.http.middlewares.asgi_throttle import ASGIThrottleMiddleware


class _OverLimitCache:
    """Cache stub that pretends every request has already blown the limit."""

    async def increment(self, key: str, *, ttl: int) -> int:
        return 10_000


def _app() -> Starlette:
    async def _root(request: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    return Starlette(
        routes=[Route("/", _root)],
        middleware=[
            Middleware(
                ASGIThrottleMiddleware,
                cache=_OverLimitCache(),
                max_requests=1,
                window_seconds=7,
            ),
        ],
    )


async def _client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=_app(), raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_throttle_returns_json_envelope_for_api_clients() -> None:
    async with await _client() as c:
        r = await c.get("/", headers={"accept": "application/json"})
    assert r.status_code == 429
    assert r.headers["retry-after"] == "7"
    assert r.headers["content-type"].startswith("application/json")
    body = r.json()
    assert body == {"message": "Too Many Requests", "code": 429}


async def test_throttle_returns_styled_html_for_browsers() -> None:
    async with await _client() as c:
        r = await c.get("/", headers={"accept": "text/html"})
    assert r.status_code == 429
    assert r.headers["retry-after"] == "7"
    assert r.headers["content-type"].startswith("text/html")
    assert "<html" in r.text
    assert "429" in r.text
    assert "Too Many Requests" in r.text


async def test_throttle_bypassed_when_under_limit() -> None:
    class _UnderLimitCache:
        async def increment(self, key: str, *, ttl: int) -> int:
            return 1

    app = Starlette(
        routes=[Route("/", lambda req: PlainTextResponse("ok"))],
        middleware=[
            Middleware(
                ASGIThrottleMiddleware,
                cache=_UnderLimitCache(),
                max_requests=5,
                window_seconds=60,
            ),
        ],
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/")
    assert r.status_code == 200
    assert r.text == "ok"


class _RecordingCache:
    """Captures every (key, count) increment — lets tests pin the
    bucket names and confirm the right ceiling was applied."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []
        self._counts: dict[str, int] = {}

    async def increment(self, key: str, *, ttl: int) -> int:
        self._counts[key] = self._counts.get(key, 0) + 1
        self.calls.append((key, self._counts[key]))
        return self._counts[key]


def _build_app(
    cache: _RecordingCache,
    *,
    max_requests: int = 2,
    authenticated_multiplier: int = 10,
    session_cookie: str = "pylar_session_id",
) -> Starlette:
    async def _root(request: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    return Starlette(
        routes=[Route("/", _root)],
        middleware=[
            Middleware(
                ASGIThrottleMiddleware,
                cache=cache,
                max_requests=max_requests,
                authenticated_multiplier=authenticated_multiplier,
                window_seconds=60,
                session_cookie=session_cookie,
            ),
        ],
    )


async def test_anonymous_and_authenticated_use_separate_buckets() -> None:
    cache = _RecordingCache()
    transport = httpx.ASGITransport(
        app=_build_app(cache), raise_app_exceptions=False,
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        await c.get("/")  # anon
        await c.get("/", headers={"cookie": "pylar_session_id=s1"})  # auth
        await c.get("/", headers={"authorization": "Bearer tok"})  # auth

    keys = {key for key, _count in cache.calls}
    # Anon bucket still keys by client IP — no better identity.
    assert any(k == "asgi-throttle:anon:ip:127.0.0.1" for k in keys)
    # Auth buckets key by the credential (hashed), not IP — two
    # users behind one NAT must get separate counters. Prefixes
    # tell session- vs token-scoped identities apart.
    assert any(":auth:session:" in k for k in keys)
    assert any(":auth:token:" in k for k in keys)
    for k in keys:
        if ":auth:" in k:
            assert "127.0.0.1" not in k, (
                "auth key must not carry the client IP"
            )


async def test_authenticated_ceiling_is_multiplier_times_base() -> None:
    cache = _RecordingCache()
    # base=2, mult=10 → anon caps at 2, auth caps at 20.
    transport = httpx.ASGITransport(
        app=_build_app(cache, max_requests=2, authenticated_multiplier=10),
        raise_app_exceptions=False,
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        auth_headers = {"cookie": "pylar_session_id=s1"}
        # 20 authenticated requests should all pass.
        for _ in range(20):
            r = await c.get("/", headers=auth_headers)
            assert r.status_code == 200
        # The 21st trips the 429 for the authenticated bucket only.
        r = await c.get("/", headers=auth_headers)
        assert r.status_code == 429


async def test_anonymous_still_capped_while_authenticated_has_headroom() -> None:
    cache = _RecordingCache()
    transport = httpx.ASGITransport(
        app=_build_app(cache, max_requests=2, authenticated_multiplier=10),
        raise_app_exceptions=False,
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        # Burn the anon budget.
        for _ in range(2):
            r = await c.get("/")
            assert r.status_code == 200
        r = await c.get("/")
        assert r.status_code == 429

        # Same client, but now presents a session cookie — different
        # bucket, different counter. Still allowed.
        r = await c.get("/", headers={"cookie": "pylar_session_id=s1"})
        assert r.status_code == 200


async def test_session_cookie_name_is_configurable() -> None:
    cache = _RecordingCache()
    transport = httpx.ASGITransport(
        app=_build_app(
            cache, max_requests=2, session_cookie="custom_sid",
        ),
        raise_app_exceptions=False,
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        # A cookie with the default name is now ignored.
        await c.get("/", headers={"cookie": "pylar_session_id=s1"})
    keys = {key for key, _count in cache.calls}
    assert any(k == "asgi-throttle:anon:ip:127.0.0.1" for k in keys)

    cache2 = _RecordingCache()
    transport2 = httpx.ASGITransport(
        app=_build_app(
            cache2, max_requests=2, session_cookie="custom_sid",
        ),
        raise_app_exceptions=False,
    )
    async with httpx.AsyncClient(transport=transport2, base_url="http://test") as c:
        # The configured name now trips the auth bucket.
        await c.get("/", headers={"cookie": "custom_sid=s1"})
    keys2 = {key for key, _count in cache2.calls}
    assert any(":auth:session:" in k for k in keys2)


async def test_two_sessions_from_one_ip_get_separate_counters() -> None:
    """Critical property of the auth bucket — NAT'd users must not
    drain each other's budget even though they share a client IP."""
    cache = _RecordingCache()
    transport = httpx.ASGITransport(
        app=_build_app(cache, max_requests=1, authenticated_multiplier=1),
        raise_app_exceptions=False,
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        # User A (session "alice") burns her budget.
        r = await c.get("/", headers={"cookie": "pylar_session_id=alice"})
        assert r.status_code == 200
        r = await c.get("/", headers={"cookie": "pylar_session_id=alice"})
        assert r.status_code == 429

        # User B, same IP, different cookie — still has a full budget.
        r = await c.get("/", headers={"cookie": "pylar_session_id=bob"})
        assert r.status_code == 200


async def test_bearer_token_identity_independent_of_cookie() -> None:
    """A request with a bearer token should key off the token, not
    fall back to any cookie value — each API client is a separate
    identity even if they accidentally share a session cookie."""
    cache = _RecordingCache()
    transport = httpx.ASGITransport(
        app=_build_app(cache, max_requests=1, authenticated_multiplier=1),
        raise_app_exceptions=False,
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get(
            "/",
            headers={
                "authorization": "Bearer token-1",
                "cookie": "pylar_session_id=shared",
            },
        )
        assert r.status_code == 200
        # Same cookie but different token — separate counter.
        r = await c.get(
            "/",
            headers={
                "authorization": "Bearer token-2",
                "cookie": "pylar_session_id=shared",
            },
        )
        assert r.status_code == 200
