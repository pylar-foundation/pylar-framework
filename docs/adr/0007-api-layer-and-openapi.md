# ADR-0007: API layer and OpenAPI generation

## Status

Accepted. Opens phase 7 of the REVIEW-3 roadmap.

## Context

Pylar already ships pydantic-based Request DTOs (ADR-0001, `pylar/validation/`)
and typed controllers. What is missing is the whole *API surface* that a
typical backend SaaS needs:

* A convention for the **response** side symmetrical to `RequestDTO` — right
  now controllers hand-build JSON via `json(post.to_dict())`.
* A **pagination envelope** that fits OpenAPI instead of Laravel's
  list-or-envelope-depending-on-serializer confusion.
* A **standard error envelope** for API routes (current paths emit the
  generic `{errors: [...]}` and `{error, ability}` shapes meant for HTML form
  flows).
* An **OpenAPI 3.1 generator** driven by the router + DTO type hints, with
  `/openapi.json` served and Swagger UI / ReDoc bundled.
* A **`pylar api:docs` console command** that dumps the spec to a file for CI
  consumption (contract testing, client codegen).

Django solves this with DRF + drf-spectacular; Laravel with API Resources +
Scribe. Both approaches suffer from redundancy (write the code, write the
serializer, write the spec). Pylar is typed end-to-end and can derive the
spec from the same DTOs and type hints that the controllers already use.

## Decision

### 1. No new resource layer — pydantic BaseModels are the serializer

Controllers return a `pydantic.BaseModel` subclass (or a `list` thereof, or
a pagination envelope). The routing compiler detects the pydantic instance
on the call site and wraps it in `JsonResponse(instance.model_dump())`.
Controllers that need full control return `Response` explicitly (unchanged
behaviour).

This means `APIResource` ≡ `pydantic.BaseModel` — no parallel hierarchy, no
`Meta` inner class, no "don't forget to add the field to two places" trap.

```python
class PostResource(BaseModel):
    id: int
    title: str
    body: str
    author: AuthorResource

class PostController:
    async def show(self, request: Request, post: Post) -> PostResource:
        return PostResource.model_validate(post, from_attributes=True)
```

### 2. Pagination envelope

New `pylar.api.Page[T]` generic built on the existing `Paginator`.
Serialised shape:

```json
{
  "data": [...],
  "meta": { "page": 2, "per_page": 20, "total": 157, "total_pages": 8 },
  "links": { "self": "/api/posts?page=2", "next": "/api/posts?page=3", "prev": "/api/posts?page=1" }
}
```

`Page[PostResource]` is a generic pydantic model — OpenAPI picks up the inner
type automatically.

### 3. Error envelope

New `pylar.api.ApiError` exception + renderer. API routes register a
mini-middleware that converts `ValidationError` / `AuthorizationError` /
`ApiError` into:

```json
{
  "error": {
    "code": "validation_error",
    "message": "The given data was invalid.",
    "details": [{"field": "title", "message": "Field required"}]
  }
}
```

The default (non-API) error rendering is unchanged — API routes opt in via
the `routes/api.py` convention or the `ApiServiceProvider`.

### 4. OpenAPI generator

A walker in `pylar.api.openapi` that:

1. Reads the compiled `Router` after bootstrap.
2. For each route: extracts method + path + the handler's signature.
3. Maps `RequestDTO` params → `requestBody` JSON Schemas
   (`dto_cls.model_json_schema()`).
4. Maps the handler's return annotation — `BaseModel`, `list[BaseModel]`,
   `Page[BaseModel]` — → `responses.200.content."application/json".schema`.
5. Maps path params + query params + header/cookie params to OpenAPI parameter
   definitions using the same metadata the router already stores on the route.
6. Emits OpenAPI 3.1 (dict-shaped, JSON-serialisable).

Published as:

* `GET /openapi.json` — spec endpoint (served by `ApiServiceProvider`).
* `GET /docs` — Swagger UI (minimal HTML, loads spec).
* `GET /redoc` — ReDoc (minimal HTML, loads spec).
* `pylar api:docs [--output path]` — dump to file for CI.

### 5. Routing convention

`routes/api.py` is the new convention (parallel to `routes/web.py`). The
framework does not force it — existing `Router` works fine — but the docs
recommend separating API routes so developers can:

* apply `ApiMiddlewarePreset` (auth-token, rate-limit, JSON-only) as a group
* route everything under `/api/v1/` for URL-based versioning
* tag every API route for the OpenAPI generator's `tags` field

Route groups keep the existing surface; the preset is a thin helper.

### 6. Versioning

**URL-prefix versioning** (`/api/v1/posts`) as the recommended approach.
Decision rationale: most teams want a clearly visible version, reverse
proxies can rewrite/route on the prefix, and it's the simplest thing that
OpenAPI tooling understands.

Header-based versioning (`Accept: application/vnd.api+json;v=2`) is
**out of scope** for phase 7 — can be bolted on later without breaking the
primary surface.

### 7. Auth-token story — deferred to phase 11 / ADR-0009

Phase 7 does **not** introduce API tokens, OAuth, or 2FA. It ships with a
pluggable `ApiAuthMiddleware` slot so ADR-0009's tokens (Sanctum-style) can
drop in without re-shaping phase 7's surface. Until phase 11 lands,
`routes/api.py` protection relies on the existing `SessionGuard` +
`RequireAuthMiddleware` combo.

### 8. Content negotiation

`Accept: application/json` is assumed. Non-JSON accept headers return 406
if the route is declared JSON-only. Handlers can still opt out by returning
a raw `Response` (e.g. `application/octet-stream` for file downloads).

## Phasing

The work ships in three coherent sub-phases, each green tests + mypy + ADR
citation in the commit:

* **7a — Foundations**: `pylar/api/` module, auto-serialise BaseModel
  returns, `Page[T]` pagination envelope, `ApiError` + renderer, no OpenAPI
  yet. Blog gets a `routes/api.py` demonstrating all four.
* **7b — OpenAPI generator**: walker over `Router`, `/openapi.json`, Swagger
  UI at `/docs`, ReDoc at `/redoc`, `pylar api:docs` command.
* **7c — Polish**: tags, operation ids, auth-slot, 406 content negotiation,
  full blog API with tests.

## Consequences

* **Backwards compat**: controllers that return `Response` keep working
  unchanged. Auto-serialisation is an *addition*, not a replacement.
* **No new dep in core**: OpenAPI generator uses pydantic's built-in
  `model_json_schema()`. Swagger UI / ReDoc are bundled via CDN links in the
  generated HTML (no bundled assets, no build step).
* **Typing holds**: the generator derives everything from type hints. The
  moment a controller's return annotation lies, the spec is wrong — which is
  strictly better than drifting Django/Laravel serializer code.
* **Migration for existing projects**: none required. Adopt
  `ApiServiceProvider` and return pydantic models when ready; don't otherwise.

## References

* REVIEW-3.md / REVIEW-3-ru.md section 7 — phase plan.
* ADR-0001 (foundation principles — no facades, strict typing).
* ADR-0005 (entry-points — future `pylar-api-*` plugins land here).
* ADR-0009 (planned — auth parity, owns the API token story).
* ADR-0013 (planned — error contract, formalises the envelope).
