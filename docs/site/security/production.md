# Production Security Checklist

This guide covers the security-critical configuration steps required
before deploying a pylar application to production. Each item is
accompanied by the rationale and the configuration surface.

---

## Secrets and Keys

### APP_KEY

Generate a cryptographically strong random key (32+ bytes).
Used by the `Encrypter` for cookie encryption and signed URLs.

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Set via environment variable or `config/app.py`.

### SESSION_SECRET

Must be at least 32 characters. Signs every session cookie with
HMAC-SHA256. A weak or leaked secret lets an attacker forge sessions.

The framework warns at startup when the secret is shorter than 16
characters or matches a known-weak default.

---

## Cookie Security

### cookie_secure

When `AppConfig.debug=False`, the session middleware **automatically
upgrades** `cookie_secure` to `True`. This ensures session cookies
are only sent over HTTPS.

To set explicitly:

```python
# config/session.py or AppServiceProvider.register()
SessionConfig(
    secret_key=env.str("SESSION_SECRET"),
    cookie_secure=True,
)
```

### SameSite

Default: `"lax"` (OWASP recommendation). Set to `"strict"` if the
application does not need cross-site navigation with session state.

### HttpOnly

Default: `True` for session cookies. The CSRF cookie is intentionally
`HttpOnly=False` so JavaScript can read it for the double-submit
pattern.

---

## CSRF Protection

Pylar uses the **double-submit cookie** pattern via `CsrfMiddleware`.

The admin panel includes CSRF protection automatically. For custom
routes, add the middleware to your route group:

```python
from pylar.auth.csrf import CsrfMiddleware

api = router.group(
    prefix="/api",
    middleware=(SessionMiddleware, CsrfMiddleware),
)
```

The SPA must read the `pylar_csrf` cookie and echo it in the
`X-CSRF-Token` header on every mutating request (POST, PUT, DELETE).

---

## Request Body Limits

`MaxBodySizeMiddleware` is mounted automatically by `HttpKernel` with
a **10 MB default**. Override in a custom kernel:

```python
from pylar.http.middlewares.max_body import MaxBodySizeMiddleware

# In your custom kernel's _collect_asgi_middleware():
StarletteMiddleware(MaxBodySizeMiddleware, max_size=50 * 1024 * 1024)
```

Requests exceeding the limit receive a `413 Content Too Large` response
before any route-level processing occurs.

---

## Rate Limiting

### ASGI-Level (DDoS Protection)

`ASGIThrottleMiddleware` is auto-mounted when a `Cache` is bound.
Configure thresholds via `ThrottleConfig`.

### Route-Level

Apply `ThrottleMiddleware` to individual route groups:

```python
group = router.group(middleware=(ThrottleMiddleware(requests=30, window=60),))
```

### Login Brute-Force

The admin login controller enforces per-session rate limiting via
`SessionGuard`. After 5 failed attempts, the endpoint returns
`429 Too Many Requests` for 60 seconds.

Configure via `SessionGuard` class attributes:

```python
SessionGuard.max_attempts = 5
SessionGuard.lockout_seconds = 60
```

---

## Password Hashing

Default: **PBKDF2-HMAC-SHA256** with 600,000 iterations (OWASP 2023).

For higher security, enable Argon2id:

```python
# config/auth.py
config = AuthConfig(
    user_model="app.models.user:User",
    password_hasher="argon2",
)
```

Requires `pip install 'pylar[auth]'`.

---

## Database

### Connection Pool Sizing

Default `pool_size=5` is conservative. For production workloads with
30+ concurrent requests, increase:

```python
# config/database.py
config = DatabaseConfig(
    url=env.str("DATABASE_URL"),
    pool_size=20,
    max_overflow=10,
)
```

Total concurrent connections = `pool_size + max_overflow`.

### pool_pre_ping

Enabled by default. Validates connections before use, preventing
stale connection errors after database restarts.

---

## Debug Mode

**Always set `debug=False` in production.** Debug mode:

- Exposes detailed tracebacks in error responses
- Disables `cookie_secure` auto-upgrade
- Enables Jinja2 template auto-reload (performance impact)

```python
# config/app.py
config = AppConfig(
    name="myapp",
    debug=env.bool("APP_DEBUG", False),
)
```

---

## Logging

Enable structured JSON logging for production log aggregation:

```python
from pylar.observability import install_json_logging

install_json_logging()
```

JSON logs include: ISO timestamp, level, logger name, message, request
ID (when available), and exception traceback.

---

## Health Checks

Pylar provides two endpoints:

- `GET /health` -- Liveness probe. Always returns 200.
- `GET /ready` -- Readiness probe. Checks database connectivity.

Configure in your container orchestrator (Kubernetes, ECS, etc.):

```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8000
readinessProbe:
  httpGet:
    path: /ready
    port: 8000
```

---

## HTTPS and Reverse Proxy

Pylar should run behind a reverse proxy (nginx, Caddy, cloud LB)
that terminates TLS. Configure `TrustProxiesMiddleware` to trust
the proxy's `X-Forwarded-*` headers:

```python
from pylar.http.middlewares import TrustProxiesMiddleware

web = router.group(middleware=(TrustProxiesMiddleware,))
```

---

## Deployment Checklist

```
[ ] APP_DEBUG=false
[ ] SESSION_SECRET: 32+ random bytes
[ ] APP_KEY: 32+ random bytes
[ ] cookie_secure=True (auto-enabled when debug=False)
[ ] CORS allowed_origins set to specific domains
[ ] DATABASE_POOL_SIZE sized for expected concurrency
[ ] JSON logging enabled
[ ] /health and /ready endpoints configured
[ ] Upload size limits reviewed (default 10MB)
[ ] CSRF middleware on all mutation routes
[ ] Rate limiting thresholds reviewed
[ ] Demo secrets rotated
[ ] Container resource limits set (CPU, memory)
[ ] TLS termination configured on reverse proxy
```
