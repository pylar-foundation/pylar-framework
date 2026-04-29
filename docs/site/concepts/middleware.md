# Middleware

Pylar middleware operates on typed `Request` / `Response` objects inside the
route pipeline. ASGI-level concerns (global rate limiting, compression) are
handled separately by Starlette middleware mounted on the kernel.

## The Middleware protocol

Every middleware implements a single async method:

```python
from pylar.http.middleware import Middleware, RequestHandler
from pylar.http.request import Request
from pylar.http.response import Response

class TimingMiddleware:
    async def handle(self, request: Request, next_handler: RequestHandler) -> Response:
        import time
        start = time.perf_counter()
        response = await next_handler(request)  # (1)!
        elapsed = time.perf_counter() - start
        response.headers["X-Response-Time"] = f"{elapsed:.4f}s"
        return response
```

1. Call `next_handler(request)` to pass the request down the pipeline.
   Omit it to short-circuit and return a response directly.

`Middleware` is a `runtime_checkable` Protocol, so any class with a matching
`handle` method qualifies -- no base class inheritance required.

## Pipeline

The `Pipeline` composes a list of middleware around a final handler. Middleware
runs in declaration order on the way **in** and in reverse on the way **out**:

```python
from pylar.http.middleware import Pipeline

middlewares = [AuthMiddleware(), TimingMiddleware()]
pipeline = Pipeline(middlewares)

response = await pipeline.send(request, final_handler)
# Order: AuthMiddleware.handle -> TimingMiddleware.handle -> final_handler
# Return: TimingMiddleware post-logic -> AuthMiddleware post-logic -> response
```

## Attaching middleware to routes

Middleware classes are attached per-route or per-group. The container constructs
them at request time so their constructors can declare dependencies:

```python
router.get("/admin", admin_handler, middleware=(AuthMiddleware, AdminMiddleware))

# Or fluent:
router.get("/admin", admin_handler).middleware(AuthMiddleware, AdminMiddleware)

# Or via group:
admin = router.group(prefix="/admin", middleware=(AuthMiddleware,))
admin.get("/dashboard", dashboard_handler, middleware=(AdminMiddleware,))
# Effective stack: AuthMiddleware -> AdminMiddleware
```

!!! tip "Stateless middleware is cached"
    If a middleware class has a no-argument constructor, the `RoutesCompiler`
    pre-builds a single instance and reuses it across requests. Middleware
    with constructor parameters is resolved from the container per request.

## Built-in middleware

Pylar ships several middleware classes ready for use:

### RequestIdMiddleware

Generates or propagates a unique `X-Request-Id` header. The ID is stored in
`request.scope["request_id"]` and in a `ContextVar` accessible via
`current_request_id()`:

```python
from pylar.http.middlewares.request_id import RequestIdMiddleware, current_request_id

router.get("/api/data", handler, middleware=(RequestIdMiddleware,))

# Inside any downstream code:
rid = current_request_id()
```

### CorsMiddleware

Handles preflight `OPTIONS` requests and adds `Access-Control-*` headers.
Subclass to tighten the policy:

```python
from pylar.http.middlewares.cors import CorsMiddleware

class AppCors(CorsMiddleware):
    allowed_origins = ("https://app.example.com",)
    allow_credentials = True
    max_age = 600
```

!!! warning
    `allow_credentials=True` with `allowed_origins=("*",)` violates the CORS
    spec. Pylar logs a warning at class definition time if you do this.

### SecureHeadersMiddleware

Attaches OWASP-recommended security headers (`X-Content-Type-Options`,
`X-Frame-Options`, `Strict-Transport-Security`, etc.). Override attributes
on a subclass to relax individual policies:

```python
from pylar.http.middlewares.secure_headers import SecureHeadersMiddleware

class AppSecureHeaders(SecureHeadersMiddleware):
    x_frame_options = "SAMEORIGIN"  # allow same-origin framing
    content_security_policy = "default-src 'self'"
```

### Other built-in middleware

| Class | Purpose |
|---|---|
| `TrimStringsMiddleware` | Strips leading/trailing whitespace from form and JSON string values. |
| `EncryptCookiesMiddleware` | Encrypts outgoing cookie values and decrypts incoming ones. |
| `MaintenanceModeMiddleware` | Returns 503 when the application is in maintenance mode. |
| `TrustProxiesMiddleware` | Trusts `X-Forwarded-*` headers from configured proxy IPs. |
| `LogRequestMiddleware` | Logs method, path, status, and duration for every request. |
| `TracingMiddleware` | Integrates with OpenTelemetry tracing spans. |

## ASGI-level rate limiting

For global rate limiting that fires **before** route matching (blocking DDoS
traffic on random URLs), mount `ASGIThrottleMiddleware` on the Starlette app:

```python
from pylar.http.middlewares.asgi_throttle import ASGIThrottleMiddleware
from starlette.middleware import Middleware as StarletteMiddleware

starlette_middleware = [
    StarletteMiddleware(
        ASGIThrottleMiddleware,
        cache=my_cache,
        max_requests=120,
        window_seconds=60,
    ),
]
```

This middleware operates at the ASGI transport level. When the cache is
unavailable, traffic passes through unthrottled rather than failing closed.
