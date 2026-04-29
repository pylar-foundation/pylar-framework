# Sessions

Pylar's session module provides signed-cookie sessions with pluggable stores, flash data, and session fixation protection.

## Configuration

```python
from pylar.session import SessionConfig, SessionMiddleware, MemorySessionStore

config = SessionConfig(
    secret_key="your-secret-key-at-least-32-chars",
    cookie_name="pylar_session_id",
    cookie_secure=True,        # require HTTPS in production
    cookie_http_only=True,
    cookie_same_site="lax",
    lifetime_seconds=1209600,  # 14 days
)

store = MemorySessionStore()
middleware = SessionMiddleware(store, config)
```

!!! warning
    `SessionConfig` logs warnings at boot time if `secret_key` is shorter than 32 characters or `cookie_secure` is `False`. Always use a strong secret in production.

## Using Sessions

Access the session via the ambient context:

```python
from pylar.session import current_session

session = current_session()

# Read
user_id = session.get("user_id")
has_cart = session.has("cart")
all_data = session.all()

# Write
session.put("user_id", 42)
session.forget("cart")
```

## Flash Data

Flash data is available only for the next request — ideal for status messages:

```python
session.flash("success", "Post created successfully!")

# Next request:
message = session.get("success")  # available once, then gone
```

## Session Fixation Protection

Regenerate the session ID after authentication to prevent fixation attacks:

```python
session.regenerate()  # rotates session id, preserves data
```

The old session ID is available via `session.regenerated_from` for logging.

## Destroying Sessions

```python
session.destroy()  # marks for deletion — store.destroy() called by middleware
```

## Session Stores

| Store | Backend | Use Case |
|---|---|---|
| `MemorySessionStore` | In-process dict | Development, testing |
| `FileSessionStore` | Filesystem (JSON) | Single-server deployments |

### Custom Store

Implement the `SessionStore` protocol:

```python
from pylar.session import SessionStore

class RedisSessionStore:
    async def read(self, session_id: str) -> dict[str, Any] | None: ...
    async def write(self, session_id: str, data: dict[str, Any], *, ttl_seconds: int) -> None: ...
    async def destroy(self, session_id: str) -> None: ...
```

## Cookie Security

The session cookie value is `<session_id>.<hmac_sha256_hex>`. The middleware verifies the HMAC on every request — tampered cookies are silently rejected (treated as a new session).

## Middleware Integration

Add `SessionMiddleware` to your middleware stack. It must run **after** `EncryptCookiesMiddleware` (if used) and **before** `AuthMiddleware`:

```python
middleware = [
    EncryptCookiesMiddleware(encrypter),
    SessionMiddleware(store, config),
    AuthMiddleware(guard),
]
```
