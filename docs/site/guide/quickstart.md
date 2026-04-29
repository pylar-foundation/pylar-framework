# Quick Start

## Create a model

```bash
pylar make:model Post
```

Edit `app/models/post.py`:

```python
from pylar.database import Model, TimestampsMixin, fields

class Post(Model, TimestampsMixin):
    class Meta:
        db_table = "posts"

    title = fields.CharField(max_length=200)
    body = fields.TextField()
    published = fields.BooleanField(default=False)
```

## Create a migration

```bash
pylar make:migration "create posts table"
pylar migrate
```

## Create a controller

```bash
pylar make:controller PostController
```

Edit `app/http/controllers/post_controller.py`:

```python
from pylar.http import Request, Response, json
from app.models.post import Post

class PostController:
    async def index(self, request: Request) -> Response:
        posts = await Post.query.where(Post.published.is_(True)).all()
        return json([p.to_dict() for p in posts])

    async def store(self, request: Request, dto: CreatePostDTO) -> Response:
        post = Post(title=dto.title, body=dto.body)
        await Post.query.save(post)
        return json(post.to_dict(), status=201)
```

## Create a DTO

```bash
pylar make:dto CreatePost
```

```python
from pylar.validation import RequestDTO

class CreatePostDTO(RequestDTO):
    title: str
    body: str
    published: bool = False
```

## Register routes

Edit `routes/api.py`:

```python
from pylar.database import DatabaseSessionMiddleware
from pylar.routing import Router
from app.http.controllers.post_controller import PostController

def register(router: Router) -> None:
    api = router.group(prefix="/api", middleware=[DatabaseSessionMiddleware])
    api.get("/posts", PostController.index)
    api.post("/posts", PostController.store)
```

## Run and test

```bash
pylar serve

# In another terminal:
curl http://localhost:8000/api/posts
curl -X POST http://localhost:8000/api/posts \
  -H "content-type: application/json" \
  -d '{"title":"Hello","body":"World"}'
```

## What's next

- [Routing](../concepts/routing.md) — groups, middleware, model binding, resource controllers
- [Database](../concepts/database.md) — QuerySet, F/Q expressions, pagination, eager loading
- [Authentication](../security/auth.md) — guards, policies, gates, CSRF
- [Queue & Jobs](../features/queue.md) — typed jobs, retry policy, middleware
