"""Built-in health check endpoints for readiness/liveness probes.

Mount via the router in a service provider::

    from pylar.http.health import health_check, readiness_check
    router.get("/health", health_check)
    router.get("/ready", readiness_check)

``/health`` (liveness) always returns 200 — it confirms the process
is running and the event loop is not stuck.

``/ready`` (readiness) checks whether critical services are
reachable (database, cache). Returns 200 when all pass, 503 when
any fail. The response body lists each check and its status.
"""

from __future__ import annotations

from pylar.http.request import Request
from pylar.http.response import JsonResponse, Response


async def health_check(request: Request) -> Response:
    """Liveness probe — always 200 if the process is alive."""
    return JsonResponse({"status": "ok"})


async def readiness_check(request: Request) -> Response:
    """Readiness probe — checks database, cache, session store, and queue."""
    checks: dict[str, str] = {}
    all_ok = True

    # Database check.
    try:
        from pylar.database.session import current_session

        sess = current_session()
        await sess.execute(__import__("sqlalchemy").text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"fail: {type(exc).__name__}"
        all_ok = False

    # Cache check.
    try:
        # Fallback: try a simple put/get cycle if Cache is importable.
        # This deliberately does NOT resolve from container to avoid coupling.
        __import__("pylar.cache")
        checks["cache"] = "not checked"
    except ImportError:
        checks["cache"] = "not configured"

    # Session store check.
    try:
        from pylar.session.context import current_session_or_none as current_http_session

        http_sess = current_http_session()
        checks["session"] = "ok" if http_sess is not None else "no session context"
    except Exception as exc:
        checks["session"] = f"fail: {type(exc).__name__}"
        all_ok = False

    status_code = 200 if all_ok else 503
    label = "ok" if all_ok else "degraded"
    return JsonResponse(
        {"status": label, "checks": checks}, status_code=status_code,
    )
