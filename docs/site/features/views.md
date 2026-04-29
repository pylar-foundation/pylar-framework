# Views

Pylar renders templates through an async `ViewRenderer` protocol backed by Jinja2 out of the box. Controllers depend on the `View` facade to turn a template name and a context dict into an `HtmlResponse` in a single call.

## Configuration

```python title="config/views.py"
from pylar.views import ViewConfig

config = ViewConfig(root="/path/to/project/resources/views", autoescape=True)
```

Templates live under the configured `root` directory. The framework defaults to `<base_path>/resources/views` when no override is provided.

## The ViewRenderer protocol

Any template engine that implements the one-method protocol can drop in as a replacement:

```python
from pylar.views import ViewRenderer

class ViewRenderer(Protocol):
    async def render(self, template: str, context: dict[str, Any]) -> str: ...
```

Pylar ships `JinjaRenderer` as its built-in implementation.

## JinjaRenderer

The renderer wraps a `jinja2.Environment` with async rendering enabled, autoescape on by default, and `trim_blocks`/`lstrip_blocks` set for clean output:

```python
from pathlib import Path
from pylar.views import JinjaRenderer

renderer = JinjaRenderer(
    root=Path("resources/views"),
    autoescape=True,
    auto_reload=True,   # set False in production for bytecode caching
)

html = await renderer.render("home.html", {"title": "Hello"})
```

When `auto_reload=False` (production), a `FileSystemBytecodeCache` is enabled under `<root>/../.jinja_cache` so templates compile once per deploy.

### Auth helpers

Call `register_auth_helpers()` after the auth layer is wired to inject `current_user()`, `is_guest()`, and optionally `can()` into every template:

```python
renderer.register_auth_helpers()
renderer.register_gate_helper(container.make(Gate))
```

```html+jinja
{% if not is_guest() %}
    Hello {{ current_user().name }}
{% endif %}

{% if can("update", post) %}
    <a href="/posts/{{ post.id }}/edit">Edit</a>
{% endif %}
```

## The View facade

Controllers depend on `View` instead of the renderer directly. It wraps rendering and response creation into one step:

```python
from pylar.views import View
from pylar.http import Request, Response


class HomeController:
    def __init__(self, views: View) -> None:
        self.views = views

    async def index(self, request: Request) -> Response:
        return await self.views.make("home.html", {"name": "world"})
```

`View.make()` renders the template and returns an `HtmlResponse`. Use `View.render()` if you need the raw string instead.

### Shared context

Register layout-wide globals that merge into every render:

```python
views.share("app_version", "1.2.0")
views.share("feature_flags", flags)
```

Shared values persist for the lifetime of the process (the `View` is a container singleton). For per-request extras use `with_()` to derive a scoped child without mutating the singleton:

```python
scoped = views.with_({"csrf_token": token})
return await scoped.make("form.html", {"fields": data})
```

## Template directory structure

```
resources/views/
    layouts/
        base.html
    home.html
    posts/
        index.html
        show.html
```

Reference templates by their path relative to the root:

```python
await views.make("posts/index.html", {"posts": posts})
```
