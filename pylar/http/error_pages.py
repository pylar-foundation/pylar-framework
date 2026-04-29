"""Default HTML error pages for 4xx / 5xx — with user override hooks.

Pylar ships one built-in HTML template for every common HTTP error
code so browser clients see a styled page instead of a JSON blob when
something goes wrong. Applications can override individual pages the
same way Laravel lets you publish
``resources/views/errors/404.blade.php`` — drop a Jinja template under
``resources/views/errors/{code}.html`` (or ``errors/{class}xx.html``
for a whole class, or ``errors/default.html`` as a catch-all) and the
resolver picks it up at render time.

Resolution order, first match wins:

1. ``register_error_page(code, handler)`` — explicit runtime override
   registered from a service provider.
2. User Jinja template at ``errors/{code}.html`` (exact code).
3. User Jinja template at ``errors/4xx.html`` / ``errors/5xx.html``.
4. User Jinja template at ``errors/default.html``.
5. Built-in per-code HTML shipped by the framework.

The resolver only runs when the client wants HTML — JSON clients
keep the structured ``{"message", "code", ...}`` envelope regardless
of overrides so APIs don't break. Debug mode bypasses the resolver
entirely and renders the rich traceback page instead.
"""

from __future__ import annotations

import html
from typing import Any

from starlette.requests import Request
from starlette.responses import HTMLResponse, Response

#: Human titles per status code — one short phrase rendered as the
#: page heading. Keep them Laravel-close so apps that mirror their
#: error pages don't need to re-translate.
STATUS_TITLES: dict[int, str] = {
    400: "Bad Request",
    401: "Unauthorized",
    402: "Payment Required",
    403: "Forbidden",
    404: "Page Not Found",
    405: "Method Not Allowed",
    408: "Request Timeout",
    409: "Conflict",
    410: "Gone",
    413: "Payload Too Large",
    414: "URI Too Long",
    415: "Unsupported Media Type",
    419: "Page Expired",
    422: "Unprocessable Entity",
    423: "Locked",
    429: "Too Many Requests",
    500: "Server Error",
    501: "Not Implemented",
    502: "Bad Gateway",
    503: "Service Unavailable",
    504: "Gateway Timeout",
}

#: Friendly one-sentence explanations per status code. Intentionally
#: non-technical — the audience is an end user landing on the page.
STATUS_MESSAGES: dict[int, str] = {
    400: "The request was malformed and could not be understood.",
    401: "You need to sign in to access this page.",
    402: "Payment is required to continue.",
    403: "You don't have permission to access this resource.",
    404: "The page you're looking for could not be found.",
    405: "This HTTP method is not supported for this URL.",
    408: "The server timed out waiting for the request.",
    409: "The request conflicts with the current state of the resource.",
    410: "The resource requested is no longer available.",
    413: "The request payload is too large to process.",
    414: "The requested URL is too long.",
    415: "The media type of the request is not supported.",
    419: "Your session has expired. Please refresh and try again.",
    422: "The submitted data could not be processed.",
    423: "The resource is locked and cannot be accessed right now.",
    429: "Too many requests. Please slow down and try again shortly.",
    500: "Something went wrong on our end.",
    501: "This feature has not been implemented yet.",
    502: "An upstream server returned an invalid response.",
    503: "The service is temporarily unavailable. Please try again later.",
    504: "An upstream server took too long to respond.",
}


#: User-registered error page renderers, keyed by status code.
#: Exported via :func:`register_error_page` — the explicit override
#: path that sits above template discovery. Each handler is an async
#: callable ``(Request, int) -> Response``.
_custom_error_pages: dict[int, Any] = {}


def register_error_page(
    status_code: int,
    handler: Any,
) -> None:
    """Register a custom error page renderer for *status_code*.

    Call from a service provider's ``boot()`` to override pylar's
    default HTML page for specific status codes. The handler runs
    only when the client wants HTML; JSON clients still receive the
    structured error envelope. Example::

        async def branded_404(request: Request, status: int) -> Response:
            html = await renderer.render("errors/404.html", {"request": request})
            return HTMLResponse(html, status_code=status)

        register_error_page(404, branded_404)

    For per-template customisation without a handler, drop a Jinja
    template at ``resources/views/errors/{code}.html`` and the
    resolver picks it up automatically.
    """
    _custom_error_pages[status_code] = handler


def get_custom_error_page(status_code: int) -> Any | None:
    """Return the user handler registered for *status_code*, if any."""
    return _custom_error_pages.get(status_code)


def clear_custom_error_pages() -> None:
    """Wipe every registered override — test-only affordance."""
    _custom_error_pages.clear()


async def resolve_error_page(
    container: Any,
    request: Request,
    *,
    status_code: int,
    detail: str | None,
) -> Response:
    """Return an HTML error page for *status_code*.

    Resolution chain: explicit registrations → user Jinja templates
    (``errors/{code}`` → ``errors/{class}xx`` → ``errors/default``)
    → built-in HTML. Callers must only invoke this when the client
    wants HTML; JSON clients go through the structured error path.
    """

    custom = get_custom_error_page(status_code)
    if custom is not None:
        return await custom(request, status_code)  # type: ignore[no-any-return]

    rendered = await _try_user_template(
        container, request, status_code=status_code, detail=detail,
    )
    if rendered is not None:
        return rendered

    return _render_builtin(status_code, detail)


async def _try_user_template(
    container: Any,
    request: Request,
    *,
    status_code: int,
    detail: str | None,
) -> Response | None:
    """Try ``errors/{code}`` → ``errors/{class}xx`` → ``errors/default``.

    Returns ``None`` when the app has no :class:`ViewRenderer` bound
    or when none of the candidate templates exists. Rendering errors
    are swallowed intentionally — a broken override must not mask
    the original HTTP error the user is already dealing with.
    """
    renderer = _maybe_renderer(container)
    if renderer is None:
        return None

    class_prefix = f"{status_code // 100}xx"
    candidates = [
        f"errors/{status_code}.html",
        f"errors/{class_prefix}.html",
        "errors/default.html",
    ]
    context = {
        "request": request,
        "status_code": status_code,
        "title": STATUS_TITLES.get(status_code, "Error"),
        "message": detail or STATUS_MESSAGES.get(status_code, ""),
    }
    for template in candidates:
        try:
            body = await renderer.render(template, context)
        except Exception:
            continue
        return HTMLResponse(body, status_code=status_code)
    return None


def _maybe_renderer(container: Any) -> Any | None:
    """Pull a :class:`ViewRenderer` out of the container if bound.

    Imported lazily so the ``pylar.http`` error handler doesn't pull
    in the view layer at module-load time — applications that don't
    use templates still benefit from the built-in pages.
    """
    if container is None:
        return None
    try:
        from pylar.views.renderer import ViewRenderer
    except ImportError:
        return None
    try:
        if not container.has(ViewRenderer):
            return None
        return container.make(ViewRenderer)
    except Exception:
        return None


def _render_builtin(status_code: int, detail: str | None) -> HTMLResponse:
    """Render the framework's default per-code HTML page."""
    title = STATUS_TITLES.get(status_code, "Error")
    message = detail or STATUS_MESSAGES.get(
        status_code, "An unexpected error occurred.",
    )
    body = _BUILTIN_TEMPLATE.format(
        status=status_code,
        title=html.escape(title),
        message=html.escape(message),
    )
    return HTMLResponse(body, status_code=status_code)


# The built-in page is a single self-contained HTML document — no
# external assets — so it renders cleanly even when the app is
# crashing hard (e.g. 502/503 from a dead backend). Palette echoes
# the debug-traceback page so ops see a consistent visual language.
_BUILTIN_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{status} {title}</title>
<style>
  html, body {{ height: 100%; }}
  body {{
    margin: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
    background: #1e1e2e;
    color: #cdd6f4;
    padding: 2rem;
    text-align: center;
  }}
  .card {{
    max-width: 32rem;
  }}
  .status {{
    font-size: 5rem;
    font-weight: 800;
    color: #f38ba8;
    letter-spacing: -0.03em;
    line-height: 1;
  }}
  .title {{
    font-size: 1.4rem;
    margin-top: 0.8rem;
    color: #cdd6f4;
    font-weight: 600;
  }}
  .message {{
    margin-top: 0.6rem;
    color: #a6adc8;
    line-height: 1.5;
  }}
  a.home {{
    margin-top: 1.6rem;
    display: inline-block;
    padding: 0.5rem 1.1rem;
    border: 1px solid #45475a;
    border-radius: 6px;
    color: #89b4fa;
    text-decoration: none;
    font-size: 0.85rem;
    transition: background 0.15s, color 0.15s, border-color 0.15s;
  }}
  a.home:hover {{
    background: #313244;
    border-color: #89b4fa;
  }}
</style>
</head>
<body>
<div class="card">
  <div class="status">{status}</div>
  <div class="title">{title}</div>
  <div class="message">{message}</div>
  <a href="/" class="home">&larr; Back to home</a>
</div>
</body>
</html>
"""
