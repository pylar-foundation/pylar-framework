# Routing

Pylar's router accepts two handler shapes -- standalone async functions and
unbound controller methods -- and normalises both into the same dispatch
pipeline.

## Defining routes

Register routes using HTTP verb methods on the `Router`:

```python
from pylar.routing.router import Router
from pylar.http.request import Request
from pylar.http.response import JsonResponse

router = Router()

async def list_posts(request: Request) -> JsonResponse:
    return JsonResponse({"posts": []})

router.get("/posts", list_posts, name="posts.index")
router.post("/posts", create_post, name="posts.store")
router.put("/posts/{post_id:int}", update_post, name="posts.update")
router.delete("/posts/{post_id:int}", delete_post, name="posts.destroy")
```

Every verb method returns a `RouteBuilder` that supports fluent chaining:

```python
router.get("/dashboard", dashboard_handler).middleware(AuthMiddleware).name("dashboard")
```

## Controller-based handlers

Pass an unbound method and the framework resolves the controller through the
container on each request -- constructor dependencies are auto-wired:

```python
class PostController:
    def __init__(self, repo: PostRepository) -> None:
        self.repo = repo

    async def index(self, request: Request) -> JsonResponse:
        posts = await self.repo.all()
        return JsonResponse({"posts": posts})

    async def show(self, request: Request, post_id: int) -> JsonResponse:
        post = await self.repo.get(post_id)
        return JsonResponse(post)

router.get("/posts", PostController.index)
router.get("/posts/{post_id:int}", PostController.show)
```

## Route groups

Groups apply a shared prefix and middleware stack to every route inside them:

```python
api = router.group(prefix="/api/v1", middleware=(AuthMiddleware,))
api.get("/users", UserController.index, name="api.users.index")
api.post("/users", UserController.store, name="api.users.store")
```

Groups nest -- prefixes concatenate and middleware accumulates:

```python
admin = api.group(prefix="/admin", middleware=(AdminMiddleware,))
admin.get("/stats", StatsController.index)
# Final path: /api/v1/admin/stats
# Middleware: AuthMiddleware -> AdminMiddleware
```

## Resource routes

Register all five REST routes for a controller in one call:

```python
router.resource("posts", PostController)
```

This generates:

| Method | Path | Handler | Name |
|---|---|---|---|
| `GET` | `/posts` | `PostController.index` | `posts.index` |
| `POST` | `/posts` | `PostController.store` | `posts.store` |
| `GET` | `/posts/{post}` | `PostController.show` | `posts.show` |
| `PUT` | `/posts/{post}` | `PostController.update` | `posts.update` |
| `DELETE` | `/posts/{post}` | `PostController.destroy` | `posts.destroy` |

Missing methods are silently skipped. Use `only` or `except_` to narrow:

```python
router.resource("posts", PostController, only=["index", "show"])
router.resource("comments", CommentController, except_=["destroy"])
```

## Path parameters and model binding

Path parameters (e.g. `{post_id:int}`) are passed to the handler by name via
`Container.call()`. When a handler parameter is typed as a `Model` subclass,
pylar auto-fetches the row by primary key and returns 404 if missing:

```python
from pylar.database.model import Model

class Post(Model):
    __tablename__ = "posts"
    # ...

async def show(request: Request, post: Post) -> JsonResponse:  # (1)!
    return JsonResponse({"title": post.title})

router.get("/posts/{post:int}", show)
```

1. The `post` parameter is typed as `Post`, so the framework calls
   `Post.query.get(path_param)` automatically. A missing row becomes a 404.

## Named routes and URL generation

Look up a route path by name with `router.url_for()`:

```python
router.get("/users/{user_id:int}/posts/{post_id:int}", handler, name="user.post")

path = router.url_for("user.post", params={"user_id": 5, "post_id": 42})
# -> "/users/5/posts/42"
```

Missing or extra parameters raise `RoutingError` immediately so typos surface
at the call site, not as a 404 later.

## WebSocket routes

```python
from starlette.websockets import WebSocket

async def chat(websocket: WebSocket, room_id: str) -> None:
    await websocket.accept()
    async for message in websocket.iter_text():
        await websocket.send_text(f"echo: {message}")

router.websocket("/ws/chat/{room_id}", chat, name="ws.chat")
```

## How RoutesCompiler wires everything

The `RoutesCompiler` translates pylar routes into Starlette routes at startup.
For each route it builds an ASGI endpoint that:

1. Opens a container **scope** (scoped bindings live for the request).
2. Constructs route-level middleware via the container.
3. Sends the request through a `Pipeline` of those middleware.
4. Invokes the `Action` (function or controller method) via `Container.call()`.
5. Catches `ValidationError` and renders it as a **422** JSON response.
6. Catches `AuthorizationError` and renders it as a **403** JSON response.

A fallback handler (`router.fallback(handler)`) catches any request that does
not match a registered route -- useful for custom 404 pages.
