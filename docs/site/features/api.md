# API Layer

Pylar's API layer (ADR-0007) turns pydantic DTOs into a typed
JSON surface: controllers return domain objects, the framework
serialises them, the OpenAPI 3.1 spec is generated from the same
type hints, Swagger UI and ReDoc are served out of the box.

## Enable the provider

```python title="config/app.py"
from pylar.api import ApiServiceProvider

config = AppConfig(
    providers=(
        # ... other providers
        ApiServiceProvider,
    ),
)
```

With the provider registered, three endpoints are mounted automatically:

| Path | Purpose |
|---|---|
| `GET /openapi.json` | The OpenAPI 3.1 spec (cached after first build) |
| `GET /docs` | Swagger UI viewer (loaded from CDN) |
| `GET /redoc` | ReDoc viewer (loaded from CDN) |

## Typed resources

Pylar uses `pydantic.BaseModel` as the sole resource abstraction — there
is no parallel `Serializer` / `APIResource` hierarchy. Define the
response shape once, pydantic validates it, OpenAPI picks it up, IDE
autocomplete reads it.

```python title="app/http/resources/post_resource.py"
from datetime import datetime
from pydantic import BaseModel, ConfigDict
from app.models.post import Post

class PostResource(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: int
    title: str
    slug: str
    body: str
    published: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, post: Post) -> "PostResource":
        return cls.model_validate(post, from_attributes=True)
```

## Controllers return domain objects

The routing compiler auto-serialises pydantic return values. Single
model, list of models, or a `Page[T]` envelope — all three work.

```python title="app/http/controllers/post_controller.py"
from pylar.api import Page
from pylar.database.paginator import Paginator
from pylar.http import Request

from app.http.resources.post_resource import PostResource
from app.models.post import Post

class PostController:
    async def show(self, request: Request, post: Post) -> PostResource:
        return PostResource.from_model(post)

    async def index(self, request: Request) -> Page[PostResource]:
        paginator: Paginator[Post] = await Post.query.paginate(
            page=int(request.query_params.get("page", 1)),
            per_page=10,
            path=str(request.url.path),
        )
        return Page.from_paginator(
            paginator,
            [PostResource.from_model(p) for p in paginator.items],
        )
```

Returning a plain `Response` is still supported — the auto-serialiser
only wraps pydantic-shaped returns. File downloads, redirects, raw
streaming responses keep working untouched.

## Pagination envelope

`Page[T]` wraps a `Paginator` in a stable JSON shape:

```json
{
  "data":  [/* resources */],
  "meta":  { "page": 2, "per_page": 20, "total": 157, "total_pages": 8 },
  "links": { "self": "...", "next": "...", "prev": "..." }
}
```

OpenAPI sees `Page[PostResource]` as a concrete schema and registers
both the envelope and the inner model under `components/schemas`.

## Error envelope

Attach `ApiErrorMiddleware` to any route group that should speak the
phase-7 error envelope:

```python title="routes/api.py"
from pylar.api import ApiErrorMiddleware

api = router.group(prefix="/api/v1", middleware=[ApiErrorMiddleware])
```

With the middleware installed, three exception types render to the
same shape:

| Exception | HTTP status | Error code |
|---|---|---|
| `pylar.validation.ValidationError` | 422 | `validation_error` |
| `pylar.auth.AuthorizationError` | 403 | `authorization_error` |
| `pylar.api.ApiError(code, message, status_code=…)` | custom | custom |

```json
{
  "error": {
    "code": "validation_error",
    "message": "The given data was invalid.",
    "details": [{"field": "title", "message": "Field required"}]
  }
}
```

Raise a custom `ApiError` for semantic errors:

```python
from pylar.api import ApiError

if post.locked:
    raise ApiError(
        "post_locked",
        "This post is locked and cannot be edited.",
        status_code=423,  # Locked
        details=[{"locked_at": post.locked_at.isoformat()}],
    )
```

## Customising the docs portal

Override `ApiDocsConfig` in a service provider to rebrand the generated
portal:

```python title="app/providers/app_service_provider.py"
from pylar.api import ApiDocsConfig

class AppServiceProvider(ServiceProvider):
    def register(self, container: Container) -> None:
        container.instance(
            ApiDocsConfig,
            ApiDocsConfig(
                title="My Shop API",
                version="2.4.1",
                description="Public storefront and checkout API.",
                servers=("https://api.myshop.com", "https://staging.myshop.com"),
                enabled=True,       # set False to hide the portal in prod
                spec_path="/openapi.json",
                swagger_path="/docs",
                redoc_path="/redoc",
            ),
        )
```

The `servers` tuple populates Swagger UI's base-URL dropdown so one
spec drives dev / staging / prod clients without rewriting the file.

## Dumping the spec for CI

```bash
pylar api:docs --output openapi.json
```

Pair it with a contract-testing tool (Spectral, Schemathesis) or a
client-code generator (openapi-generator, fern) in CI. Running without
`--output` prints the spec to stdout — handy for `pylar api:docs | jq`.

## Versioning

URL-prefix versioning is the recommended approach:

```python
v1 = router.group(prefix="/api/v1", middleware=[ApiErrorMiddleware])
v1.get("/posts", PostController.v1_index)

v2 = router.group(prefix="/api/v2", middleware=[ApiErrorMiddleware])
v2.get("/posts", PostController.v2_index)
```

Header-based versioning (`Accept: application/vnd.api+json;v=2`) is out
of scope for the current phase — can be layered on top without reshaping
the primary surface.

## Authentication

Phase 7 does not ship an API-token guard. Until ADR-0009 / phase 11
lands:

* For **session-cookie** APIs (same-origin), reuse `SessionGuard` +
  `RequireAuthMiddleware`.
* For **bearer tokens**, implement a custom middleware that resolves
  the `Authorization` header and attaches the user to the request
  scope — pylar's middleware pipeline is typed and auto-wired, so
  swapping in token auth is mechanical.

When ADR-0009 lands, the built-in API token guard drops into the same
middleware slot without reshaping the rest of the surface.
