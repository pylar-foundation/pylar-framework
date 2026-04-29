# Tutorial: Build a Blog

This walk-through builds a small blog with posts, comments, and a
typed JSON API on top of pylar. The finished code mirrors the
`examples/blog/` reference project — consult it when a step feels
condensed.

!!! info "Prerequisites"
    * Python 3.12+
    * `uv` (or `pip`), Postgres or SQLite for the database
    * Basic familiarity with pydantic and SQLAlchemy 2.0

## 1. Bootstrap

```bash
pip install pylar[serve,postgres]
pylar new myblog
cd myblog
```

The generator lays down the standard structure:

```
myblog/
├── app/
│   ├── http/         controllers, requests, resources
│   ├── models/       domain models
│   └── providers/    ServiceProviders
├── config/           database.py, app.py, queue.py, …
├── database/
│   └── migrations/   alembic revisions
└── routes/
    ├── api.py        JSON API
    └── web.py        HTML flows
```

## 2. Define the Post model

```python title="app/models/post.py"
from pylar.database import Model, TimestampsMixin, fields

class Post(Model, TimestampsMixin):
    class Meta:
        db_table = "posts"

    title = fields.CharField(max_length=200)
    slug = fields.SlugField(max_length=240, unique=True)
    body = fields.TextField()
    published = fields.BooleanField(default=False)

    comments = fields.HasMany(
        model="app.models.comment.Comment", back_populates="post"
    )
```

Generate the migration and apply it:

```bash
pylar make:migration create_posts
pylar migrate
```

## 3. Request DTO

```python title="app/http/requests/create_post.py"
from pylar.validation import RequestDTO

class CreatePostDTO(RequestDTO):
    title: str
    body: str
    published: bool = False
```

The routing layer parses the JSON body into this typed object
automatically and returns HTTP 422 with the error envelope if the
payload is invalid.

## 4. Resource (response shape)

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

## 5. Controller

```python title="app/http/controllers/post_controller.py"
from pylar.api import Page
from pylar.database import transaction
from pylar.database.paginator import Paginator
from pylar.http import Request

from app.http.requests.create_post import CreatePostDTO
from app.http.resources.post_resource import PostResource
from app.models.post import Post

class PostController:
    async def index(self, request: Request) -> Page[PostResource]:
        page = int(request.query_params.get("page", 1))
        paginator: Paginator[Post] = await Post.query.paginate(
            page=page, per_page=10, path=str(request.url.path),
        )
        return Page.from_paginator(
            paginator, [PostResource.from_model(p) for p in paginator.items],
        )

    async def show(self, request: Request, post: Post) -> PostResource:
        return PostResource.from_model(post)

    async def store(self, request: Request, dto: CreatePostDTO) -> PostResource:
        async with transaction():
            post = Post(title=dto.title, body=dto.body, published=dto.published)
            await Post.query.save(post)
        return PostResource.from_model(post)
```

Notice the three return types: `PostResource`, `Page[PostResource]`,
and the DTO-driven `store` — the framework auto-serialises all three.

## 6. Routes

```python title="routes/api.py"
from pylar.api import ApiErrorMiddleware
from pylar.routing import Router

from app.http.controllers.post_controller import PostController

def register(router: Router) -> None:
    api = router.group(prefix="/api/v1", middleware=[ApiErrorMiddleware])
    api.get("/posts", PostController().index, name="posts.index")
    api.get("/posts/{post_id:int}", PostController().show, name="posts.show")
    api.post("/posts", PostController().store, name="posts.store")
```

## 7. Wire the service provider

Add `ApiServiceProvider` to the provider list so `/openapi.json`,
`/docs`, and `/redoc` are mounted:

```python title="config/app.py" hl_lines="3 16"
from pylar.foundation import AppConfig
from pylar.http import HttpServiceProvider
from pylar.api import ApiServiceProvider
# ... other imports

config = AppConfig(
    name="myblog",
    providers=(
        DatabaseServiceProvider,
        MigrationsServiceProvider,
        CacheServiceProvider,
        EncryptionServiceProvider,
        SessionServiceProvider,
        StorageServiceProvider,
        HttpServiceProvider,
        ApiServiceProvider,
        ViewServiceProvider,
        AuthServiceProvider,
        AppServiceProvider,
        RouteServiceProvider,
    ),
)
```

## 8. Run it

```bash
pylar serve
```

* `http://localhost:8000/api/v1/posts` — paginated list
* `http://localhost:8000/api/v1/posts/1` — single post
* `http://localhost:8000/openapi.json` — OpenAPI 3.1 spec
* `http://localhost:8000/docs` — Swagger UI
* `http://localhost:8000/redoc` — ReDoc

## 9. Add a background job

A publish action that flips `published=True` off the request path:

```python title="app/jobs/publish_post.py"
from pylar.database import transaction
from pylar.queue import Job, JobPayload

from app.models.post import Post

class PublishPostPayload(JobPayload):
    post_id: int

class PublishPostJob(Job[PublishPostPayload]):
    payload_type = PublishPostPayload
    queue = "high"   # latency-sensitive

    async def handle(self, payload: PublishPostPayload) -> None:
        async with transaction():
            post = await Post.query.get(payload.post_id)
            if post.published:
                return
            post.published = True
            await Post.query.save(post)
```

Dispatch it from a controller:

```python
await self.dispatcher.dispatch(
    PublishPostJob, PublishPostPayload(post_id=post.id)
)
```

Run workers:

```bash
pylar queue:work --queue=high,default
# or autoscaling:
pylar queue:supervisor
```

## 10. Write a test

```python title="tests/test_posts.py"
async def test_create_post(client):
    r = await client.post("/api/v1/posts", json={
        "title": "Hello", "body": "world", "published": True,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Hello"
    assert body["slug"] == "hello"
```

Run it:

```bash
pylar test
```

## What's next

* Browse the [API Layer feature doc](../features/api.md) for the
  full resource / pagination / error-envelope surface.
* Read [Queue & Jobs](../features/queue.md) for retries, middleware,
  and the `queue:supervisor` autoscaler.
* Consult the [ADRs](../architecture/adrs.md) for the architectural
  choices behind every module.
