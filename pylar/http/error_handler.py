"""Centralised error rendering — debug page or clean production response.

When ``debug=True`` the handler renders a rich HTML page with:
* the exception class and message
* a syntax-highlighted code snippet around the failing line
* the full traceback with file paths and line numbers
* request details (method, URL, headers, query params)

When ``debug=False`` the handler renders a minimal JSON or plain-text
response with no internal details — model names, primary keys,
traceback frames, and database URLs are all redacted.

The handler is mounted by :class:`HttpKernel` as Starlette's
``exception_handlers`` mapping, so it catches everything that
propagates out of the middleware pipeline — including unhandled
``Exception``, ``HttpException``, ``ValidationError``, and
``AuthorizationError``.
"""

from __future__ import annotations

import html
import linecache
import traceback
from typing import Any

from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response

from pylar.http.error_pages import (
    register_error_page as register_error_page,  # re-exported
)
from pylar.http.error_pages import resolve_error_page


def make_error_handlers(
    debug: bool,
    container: Any | None = None,
) -> dict[Any, Any]:
    """Return the exception handler dict for Starlette.

    *container* is the application IoC container — passed through so
    the HTML error-page resolver can look up a :class:`ViewRenderer`
    for user-overridden ``resources/views/errors/*.html`` templates.

    The dict maps ``StarletteHTTPException`` to a handler that
    renders a debug HTML page (in debug mode), a JSON envelope (for
    JSON clients in both modes), or a styled HTML error page
    (user-overridden or built-in) for browser clients in production.
    The ``Exception`` key is also registered so Starlette routes it
    to ``ServerErrorMiddleware``'s ``handler`` parameter — which
    fires regardless of ``debug`` mode.
    """

    async def handle_http_exception(
        request: Request, exc: StarletteHTTPException
    ) -> Response:
        extra_headers = dict(exc.headers) if exc.headers else {}
        if debug and not _wants_json(request):
            debug_resp = _debug_response(request, exc, exc.status_code)
            for k, v in extra_headers.items():
                debug_resp.headers[k] = v
            return debug_resp
        # JSON clients always get JSON — in both debug and production.
        if _wants_json(request):
            return _json_error(exc.status_code, str(exc.detail), exc, debug)
        # HTML clients: custom override → user Jinja template → built-in.
        detail = str(exc.detail) if exc.detail else None
        html_resp = await resolve_error_page(
            container, request, status_code=exc.status_code, detail=detail,
        )
        for k, v in extra_headers.items():
            html_resp.headers[k] = v
        return html_resp

    async def handle_exception(
        request: Request, exc: Exception
    ) -> Response:
        if debug and not _wants_json(request):
            return _debug_response(request, exc, 500)
        if _wants_json(request):
            return _json_error(500, "Internal Server Error", exc, debug)
        return await resolve_error_page(
            container, request, status_code=500, detail=None,
        )

    return {
        StarletteHTTPException: handle_http_exception,
        Exception: handle_exception,
    }


# -------------------------------------------------------- content negotiation


def _wants_json(request: Request) -> bool:
    """Return ``True`` when the client prefers a JSON response.

    Checks the ``Accept`` header for ``application/json`` or common
    API indicators (``X-Requested-With: XMLHttpRequest``, paths
    starting with ``/api/``).  When ``Accept`` is absent or ``*/*``
    the function falls back to path-based detection so API routes
    get JSON and browser requests get HTML.
    """
    accept = request.headers.get("accept", "")
    if "application/json" in accept:
        return True
    # XHR / fetch from JavaScript typically sends this header.
    if request.headers.get("x-requested-with", "").lower() == "xmlhttprequest":
        return True
    # Heuristic: paths containing /api/ are almost always JSON consumers
    # (covers /api/..., /admin/api/..., /v1/api/..., etc.).
    if "/api/" in request.url.path:
        return True
    # Wildcard accept with no text/html preference — treat as non-JSON.
    return False


# ----------------------------------------------------------- JSON errors


_STATUS_MESSAGES: dict[int, str] = {
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    422: "Unprocessable Entity",
    429: "Too Many Requests",
    500: "Internal Server Error",
    503: "Service Unavailable",
}


def _json_error(
    status_code: int,
    detail: str,
    exc: BaseException,
    debug: bool,
) -> Response:
    """Build a JSON error response with ``message``, ``code``, and optional ``trace``.

    When ``debug=True`` the full traceback is included so API clients
    (Postman, curl, the Vue.js admin SPA) can display it in dev mode.
    In production the trace is omitted.
    """
    message = detail if detail and detail != "None" else _STATUS_MESSAGES.get(status_code, "Error")
    body: dict[str, object] = {
        "message": message,
        "code": status_code,
    }
    if debug:
        body["trace"] = traceback.format_exception(type(exc), exc, exc.__traceback__)

    headers: dict[str, str] = {}
    if isinstance(exc, StarletteHTTPException) and exc.headers:
        headers = dict(exc.headers)

    return JSONResponse(body, status_code=status_code, headers=headers)


# ----------------------------------------------------------- debug page


def _debug_response(
    request: Request, exc: BaseException, status_code: int
) -> HTMLResponse:
    """Render a rich error page with traceback and request info."""
    tb = traceback.extract_tb(exc.__traceback__)
    frames_html = _render_frames(tb)
    exception_class = type(exc).__qualname__
    exception_message = html.escape(str(exc))
    request_html = _render_request(request)

    body = _DEBUG_TEMPLATE.replace("{{exception_class}}", exception_class)
    body = body.replace("{{exception_message}}", exception_message)
    body = body.replace("{{status_code}}", str(status_code))
    body = body.replace("{{frames}}", frames_html)
    body = body.replace("{{request_info}}", request_html)

    return HTMLResponse(body, status_code=status_code)


def _render_frames(tb: traceback.StackSummary) -> str:
    parts: list[str] = []
    for frame in reversed(tb):
        filename = html.escape(frame.filename)
        lineno = frame.lineno or 0
        name = html.escape(frame.name)
        code_lines = _get_code_context(frame.filename, lineno, context=7)
        parts.append(
            f'<div class="frame">'
            f'<div class="frame-header">'
            f'<span class="file">{filename}</span>'
            f'<span class="line">:{lineno}</span>'
            f' in <span class="func">{name}</span>'
            f'</div>'
            f'<pre class="code">{code_lines}</pre>'
            f'</div>'
        )
    return "\n".join(parts)


def _get_code_context(filename: str, lineno: int, context: int = 7) -> str:
    lines: list[str] = []
    start = max(1, lineno - context)
    end = lineno + context + 1
    for i in range(start, end):
        line = linecache.getline(filename, i)
        if not line:
            continue
        escaped = html.escape(line.rstrip())
        cls = ' class="highlight"' if i == lineno else ""
        lines.append(f'<span{cls}><span class="ln">{i:4d}</span> {escaped}</span>')
    return "\n".join(lines)


def _render_request(request: Request) -> str:
    parts: list[str] = []
    parts.append(f"<tr><td>Method</td><td>{html.escape(request.method)}</td></tr>")
    parts.append(f"<tr><td>URL</td><td>{html.escape(str(request.url))}</td></tr>")
    if request.client:
        parts.append(f"<tr><td>Client</td><td>{html.escape(request.client.host)}</td></tr>")
    for key, value in sorted(request.headers.items()):
        if key.lower() in ("authorization", "cookie"):
            value = "***"
        parts.append(
            f"<tr><td>{html.escape(key)}</td><td>{html.escape(value)}</td></tr>"
        )
    return "\n".join(parts)


# ---------------------------------------------------------------- template


_DEBUG_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{exception_class}} — pylar</title>
<style>
  :root {
    --bg: #1e1e2e;
    --surface: #282840;
    --text: #cdd6f4;
    --muted: #6c7086;
    --red: #f38ba8;
    --green: #a6e3a1;
    --blue: #89b4fa;
    --yellow: #f9e2af;
    --peach: #fab387;
    --highlight-bg: rgba(243,139,168,0.12);
    --border: #45475a;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: ui-monospace, "Cascadia Code", "Fira Code", Menlo, monospace;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    padding: 0;
  }
  .header {
    background: var(--red);
    color: var(--bg);
    padding: 1.5rem 2rem;
  }
  .header h1 { font-size: 1.3rem; font-weight: 700; }
  .header .message { font-size: 1rem; margin-top: 0.3rem; opacity: 0.9; }
  .header .status { float: right; font-size: 2rem; font-weight: 800; opacity: 0.3; }
  .container { max-width: 1200px; margin: 0 auto; padding: 1.5rem 2rem; }
  h2 {
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--muted);
    margin: 2rem 0 0.8rem;
    border-bottom: 1px solid var(--border);
    padding-bottom: 0.4rem;
  }
  .frame {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    margin-bottom: 1rem;
    overflow: hidden;
  }
  .frame-header {
    padding: 0.6rem 1rem;
    font-size: 0.8rem;
    border-bottom: 1px solid var(--border);
    background: rgba(0,0,0,0.15);
  }
  .frame-header .file { color: var(--blue); }
  .frame-header .line { color: var(--yellow); }
  .frame-header .func { color: var(--green); }
  pre.code {
    padding: 0.5rem 0;
    font-size: 0.8rem;
    overflow-x: auto;
    line-height: 1.7;
  }
  pre.code span { display: block; padding: 0 1rem; }
  pre.code span.highlight { background: var(--highlight-bg); }
  pre.code .ln { color: var(--muted); margin-right: 1rem; user-select: none; }
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.8rem;
  }
  table td {
    padding: 0.35rem 0.8rem;
    border-bottom: 1px solid var(--border);
    vertical-align: top;
  }
  table td:first-child {
    color: var(--peach);
    white-space: nowrap;
    width: 180px;
  }
  table td:last-child { word-break: break-all; }
  .footer {
    text-align: center;
    color: var(--muted);
    font-size: 0.7rem;
    padding: 2rem 0;
  }
</style>
</head>
<body>
<div class="header">
  <span class="status">{{status_code}}</span>
  <h1>{{exception_class}}</h1>
  <div class="message">{{exception_message}}</div>
</div>
<div class="container">
  <h2>Stack Trace</h2>
  {{frames}}
  <h2>Request</h2>
  <table>{{request_info}}</table>
  <div class="footer">pylar debug error handler &mdash; set debug=False in production</div>
</div>
</body>
</html>
"""
