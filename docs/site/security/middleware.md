# Security Middleware Stack

Pylar's security is assembled from composable middleware. The order matters -- each layer depends on the one before it.

## Recommended Stack Order

```python
from pylar.http.middlewares.secure_headers import SecureHeadersMiddleware
from pylar.http.middlewares.encrypt_cookies import EncryptCookiesMiddleware
from pylar.http.middlewares.cors import CorsMiddleware
from pylar.session import SessionMiddleware
from pylar.auth import AuthMiddleware, RequireAuthMiddleware, CsrfMiddleware

# Global middleware (runs on every request, outermost first):
global_middleware = [
    SecureHeadersMiddleware(),        # 1. Security headers on every response
    CorsMiddleware(),                 # 2. CORS before anything reads the body
    EncryptCookiesMiddleware(enc),    # 3. Decrypt cookies before session reads them
    SessionMiddleware(store, config), # 4. Load session (AuthMiddleware needs it)
    AuthMiddleware(guard),            # 5. Resolve the current user
    CsrfMiddleware(),                 # 6. CSRF after session, before controllers
]
```

## SecureHeadersMiddleware

Adds OWASP-recommended headers to every response. Override attributes on a subclass to tune:

```python
from pylar.http.middlewares.secure_headers import SecureHeadersMiddleware

class AppSecureHeaders(SecureHeadersMiddleware):
    x_frame_options = "SAMEORIGIN"          # allow same-origin framing
    strict_transport_security = "max-age=31536000; includeSubDomains"
    content_security_policy = "default-src 'self'"
```

Default headers: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Strict-Transport-Security`, `Referrer-Policy: strict-origin-when-cross-origin`.

## CorsMiddleware

Handles preflight `OPTIONS` requests and sets `Access-Control-*` headers. Secure by default -- subclass to open up:

```python
from pylar.http.middlewares.cors import CorsMiddleware

class AppCors(CorsMiddleware):
    allowed_origins = ("https://app.example.com",)
    allow_credentials = True
    max_age = 600
```

!!! warning
    Setting `allow_credentials = True` with `allowed_origins = ("*",)` violates the CORS spec. Pylar logs a warning at class definition time if you do this.

## SessionMiddleware

Loads the session from the configured store (memory, file, or custom) via a signed cookie. The cookie value is `<session_id>.<hmac_sha256>` -- tampered cookies are rejected. See [Sessions](../features/sessions.md) for store configuration.

## AuthMiddleware & RequireAuthMiddleware

`AuthMiddleware` resolves the user but allows anonymous requests through. Add `RequireAuthMiddleware` on routes that need a logged-in user:

```python
# Public routes -- AuthMiddleware populates current_user_or_none()
public = router.group(middleware=[AuthMiddleware(guard)])

# Protected routes -- anonymous requests get 401
protected = router.group(middleware=[
    AuthMiddleware(guard),
    RequireAuthMiddleware(),
])
```

## CsrfMiddleware

Stateless double-submit cookie protection. On safe methods (`GET`, `HEAD`, `OPTIONS`) it sets a `pylar_csrf` cookie. On mutating methods it verifies the cookie matches the `X-CSRF-Token` header:

```python
from pylar.auth import CsrfMiddleware

csrf = CsrfMiddleware(
    cookie_name="pylar_csrf",
    header_name="x-csrf-token",
    secure=True,          # require HTTPS in production
    same_site="lax",
)
```

The token rotates after every mutating request. JavaScript reads the cookie (it is not `HttpOnly`) and echoes it into the header.

## ASGI-Level Rate Limiting

`ASGIThrottleMiddleware` runs before route matching, throttling by IP at the transport level. DDoS traffic hitting random URLs is rejected before any middleware or database work:

```python
from pylar.http.middlewares.asgi_throttle import ASGIThrottleMiddleware
from starlette.middleware import Middleware

app = Starlette(
    middleware=[
        Middleware(ASGIThrottleMiddleware, cache=cache,
                   max_requests=120, window_seconds=60),
    ],
)
```

When the cache is unavailable, traffic passes through rather than failing closed -- availability over strictness.

## EncryptCookiesMiddleware

Encrypts outgoing `Set-Cookie` values and decrypts incoming cookies using the `Encrypter`. Must run **before** `SessionMiddleware` so the session cookie is decrypted before the session layer reads it. Exclude cookies that client-side JavaScript needs to read:

```python
from pylar.http.middlewares.encrypt_cookies import EncryptCookiesMiddleware

class AppEncryptCookies(EncryptCookiesMiddleware):
    except_cookies = ("pylar_csrf", "analytics_consent")
```
