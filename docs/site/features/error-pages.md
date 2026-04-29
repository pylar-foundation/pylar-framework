# Error Pages

Pylar ships a styled HTML page for every common 4xx/5xx response so
browser clients see a coherent error screen instead of a raw JSON
envelope when something goes wrong. The pages live in
`pylar.http.error_pages` and are routed through the same handler that
renders the debug traceback — so production errors look polished while
development keeps its rich inspector.

Built-in pages exist for the full Laravel-parity set:

`400`, `401`, `402`, `403`, `404`, `405`, `408`, `409`, `410`, `413`,
`414`, `415`, `419`, `422`, `423`, `429`, `500`, `501`, `502`, `503`,
`504`.

## When built-ins fire

The error resolver only runs in two situations:

- `debug=False` — in production, any unhandled `HTTPException` or
  uncaught `Exception` is funnelled through the handler.
- The client prefers HTML. JSON clients are detected automatically and
  always get the structured envelope instead (see below).

When `debug=True` and the client is a browser, pylar still renders the
full traceback page with syntax-highlighted frames — the resolver is
bypassed entirely so you never lose debugging information in development.

## Content negotiation

The handler inspects the request before deciding which surface to
render. A client is considered a JSON consumer when any of the
following is true:

- `Accept` header contains `application/json`.
- `X-Requested-With: XMLHttpRequest` is present (jQuery, fetch).
- The request path contains `/api/` (covers `/api/...`, `/v1/api/...`,
  `/admin/api/...`).

JSON clients always get the `{"message", "code"}` envelope regardless
of any override you register — APIs should not start returning HTML
when someone drops a custom 404 template in.

## Customising a single status code

The simplest override is a Jinja template under
`resources/views/errors/`. Drop a file named after the status code and
the resolver picks it up on the next request:

```
resources/views/errors/404.html
resources/views/errors/500.html
```

The template receives four variables:

| Name | Type | Notes |
|---|---|---|
| `request` | `Request` | The originating request |
| `status_code` | `int` | e.g. `404` |
| `title` | `str` | Short phrase, e.g. `"Page Not Found"` |
| `message` | `str` | One-sentence description |

```jinja
{# resources/views/errors/404.html #}
<!doctype html>
<html>
  <body>
    <h1>{{ status_code }} &mdash; {{ title }}</h1>
    <p>{{ message }}</p>
    <a href="/">Home</a>
  </body>
</html>
```

## Class-level and default fallbacks

When an exact-code template is missing, pylar walks two more
candidates before falling back to the built-in page:

1. `errors/4xx.html` / `errors/5xx.html` — one template for an entire
   class of errors.
2. `errors/default.html` — a single catch-all for any status code.

Use `4xx.html` when all your client-error pages share the same layout
and only the title/message differ. Use `default.html` when you want
one branded page to replace every built-in.

## Runtime override via `register_error_page`

When you need Python logic (e.g. to pull a translated string, or call
out to a different renderer) rather than a static template, register
a handler from a service provider's `boot()`:

```python
from pylar.foundation import Container, ServiceProvider
from pylar.http import register_error_page
from pylar.http.response import html
from starlette.requests import Request
from starlette.responses import Response


async def branded_404(request: Request, status: int) -> Response:
    return html(
        "<h1>Nothing to see here</h1>",
        status_code=status,
    )


class AppServiceProvider(ServiceProvider):
    async def boot(self, container: Container) -> None:
        register_error_page(404, branded_404)
```

Registered handlers sit **above** template discovery, so a handler for
`404` wins even if `resources/views/errors/404.html` also exists.

## Resolution order

First match wins:

1. `register_error_page(code, handler)` — explicit runtime override.
2. `resources/views/errors/{code}.html` — exact template.
3. `resources/views/errors/{4xx|5xx}.html` — class template.
4. `resources/views/errors/default.html` — catch-all template.
5. Built-in per-code HTML shipped by pylar.

Debug mode short-circuits this chain and renders the traceback page
instead. JSON clients skip the chain entirely.

## 429 from the ASGI throttle

`ASGIThrottleMiddleware` fires *before* route matching — random-path
DDoS traffic is rejected without ever touching the router. That path
goes through the same `resolve_error_page` helper as every other
error, so a custom `resources/views/errors/429.html` (or an explicit
`register_error_page(429, ...)`) is honoured even for the ASGI-level
short-circuit. The middleware adds the `Retry-After` header on top of
whichever branch renders the response.
