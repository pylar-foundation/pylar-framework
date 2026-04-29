# Database

Pylar's database layer wraps SQLAlchemy 2.0 with Laravel-style ergonomics:
`Model` for entities, `Manager` for per-model query entry points, `QuerySet`
for chainable queries, and observers for lifecycle hooks.

## Defining models

Two column declaration styles are supported and can be mixed freely:

=== "Django-style fields"

    ```python
    from pylar.database.model import Model
    from pylar.database import fields

    class Post(Model):
        class Meta:
            db_table = "posts"

        title = fields.CharField(max_length=200)
        body = fields.TextField()
        published = fields.BooleanField(default=False)
        created_at = fields.DateTimeField(auto_now_add=True)
        author_id = fields.ForeignKey(to="users.id", on_delete="CASCADE")
    ```

=== "SQLAlchemy 2.0 typed mappings"

    ```python
    from pylar.database.model import Model
    from sqlalchemy.orm import Mapped, mapped_column

    class Post(Model):
        __tablename__ = "posts"
        id: Mapped[int] = mapped_column(primary_key=True)
        title: Mapped[str]
        body: Mapped[str]
        published: Mapped[bool] = mapped_column(default=False)
    ```

!!! info "Auto primary key"
    When no primary key column is declared, pylar adds an auto-incrementing
    integer `id` column automatically.

### Available field types

| Field | Python type | Notes |
|---|---|---|
| `IntegerField`, `BigIntegerField` | `int` | |
| `FloatField` | `float` | |
| `DecimalField` | `Decimal` | `max_digits`, `decimal_places` |
| `CharField` | `str` | `max_length` (default 255) |
| `TextField` | `str` | Unbounded text |
| `EmailField` | `str` | CharField capped at 254 chars |
| `BooleanField` | `bool` | |
| `DateTimeField` | `datetime` | `auto_now_add=True` for creation timestamp |
| `DateField` | `date` | |
| `JSONField`, `JSONBField` | `dict` | JSONB on Postgres, JSON elsewhere |
| `UuidField` | `uuid.UUID` | `auto=True` to generate with `uuid4` |
| `ForeignKey` | `int` or `UUID` | `to="table.column"`, `on_delete`, `as_uuid` |
| `EnumField` | `Enum` | `enum_type=MyEnum` |
| `ArrayField` | `list` | `inner=fields.CharField(...)` |

### Column comments

Every field accepts a `comment: str | None = None` argument. When set,
the string is persisted on the SQL column (SQLAlchemy's native
`comment=` kwarg, which emits `COMMENT ON COLUMN` on dialects that
support it) so DBAs see the description in the catalog. The admin
panel also reads the comment as the column's display label.

```python
class Post(Model):
    title = fields.CharField(max_length=200, comment="Headline shown on listings")
    published = fields.BooleanField(default=False, comment="Visible to readers")
```

Admin label priority, first match wins:

1. i18n translation key `admin.model.<slug>.field.<name>`.
2. `Field.comment`.
3. The raw attribute name.

## Querying with Manager and QuerySet

Every `Model` subclass has a `query` class attribute (a `Manager`) that opens
chainable queries:

```python
# All posts
posts = await Post.query.all()

# Filtered, ordered, limited
recent = await Post.query.where(
    Post.published == True
).order_by(Post.created_at.desc()).limit(10).all()

# Single row by primary key (raises RecordNotFoundError if missing)
post = await Post.query.get(42)

# First matching row (returns None if missing)
post = await Post.query.where(Post.title == "Hello").first()

# Count
n = await Post.query.where(Post.published == True).count()
```

### Eager loading with `with_`

Prevent N+1 queries by eager-loading relationships:

```python
posts = await Post.query.with_("author", "tags").all()
for post in posts:
    print(post.author.name)  # no additional query
```

Nested paths are supported: `with_("author.profile", "comments.user")`.

### F and Q expressions

Build dynamic predicates with Django-style `F` (column reference) and `Q`
(composable predicate):

```python
from pylar.database.expressions import F, Q

# Q with kwargs -- supports lookup operators
await User.query.where(Q(active=True) | Q(role="admin")).all()
await User.query.where(Q(email__icontains="@corp.com")).all()
await User.query.where(~Q(banned=True)).all()

# F for column references in comparisons
await User.query.where(F("login_count") > 10).all()
```

Supported lookup suffixes: `eq` (default), `ne`, `gt`, `ge`, `lt`, `le`,
`in`, `contains`, `icontains`, `startswith`, `endswith`, `isnull`.

## Writing records

The `Manager` provides single-row write methods that fire observer hooks:

```python
from pylar.database.transaction import transaction

async with transaction() as session:
    post = Post(title="Hello", body="World")
    await Post.query.save(post)      # INSERT + flush

    post.title = "Updated"
    await Post.query.save(post)      # UPDATE + flush

    await Post.query.delete(post)    # DELETE (or soft-delete)
```

## Ambient session

Pylar uses a `ContextVar`-backed ambient session. The `DatabaseSessionMiddleware`
sets it for HTTP requests; use `use_session()` in CLI commands and tests:

```python
from pylar.database.session import current_session, use_session

# Inside an HTTP handler -- session is already available:
session = current_session()

# In a CLI command or test:
async with use_session(connection_manager) as session:
    users = await User.query.all()
```

Accessing `current_session()` outside an active scope raises
`NoActiveSessionError` with a clear message.

## Transactions

The `transaction()` context manager commits on success and rolls back on
exception:

```python
from pylar.database.transaction import transaction

async with transaction() as session:
    user = User(email="new@example.com")
    await User.query.save(user)
    profile = Profile(user_id=user.id)
    await Profile.query.save(profile)
    # Both rows committed together

async with transaction(isolation_level="SERIALIZABLE") as session:
    # Runs under SERIALIZABLE isolation
    ...
```

## Observers

Observers hook into the model lifecycle. Each hook is an async no-op by
default -- override only the ones you need:

```python
from pylar.database.observer import Observer

class PostObserver(Observer["Post"]):
    async def creating(self, post: Post) -> None:
        post.slug = slugify(post.title)

    async def deleted(self, post: Post) -> None:
        await search_index.remove(post.id)
```

Attach observers from a service provider's `boot` phase:

```python
class AppServiceProvider(ServiceProvider):
    async def boot(self, container: Container) -> None:
        Post.observe(container.make(PostObserver))
```

Hook firing order on save: `saving` > `creating`/`updating` > flush >
`created`/`updated` > `saved`. Bulk operations (`QuerySet.delete()`) bypass
observers intentionally.
