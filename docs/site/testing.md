# Testing

Pylar ships a `pylar.testing` module with helpers purpose-built for pytest.
Tests run against an in-memory SQLite database, drive HTTP through
`httpx.ASGITransport` (no real server), and use `pytest-asyncio` in **auto**
mode so every `async def` test is picked up without a decorator.

## Quick start

Install the dev extras and run the suite:

```bash
uv run pytest -q
```

## Creating a test application

`create_test_app` builds a lightweight `Application` with sensible defaults
and no config directory on disk:

```python
from pylar.testing import create_test_app

app = create_test_app(providers=[MyServiceProvider])
await app.bootstrap()
```

| Parameter    | Type                              | Default              |
|--------------|-----------------------------------|----------------------|
| `providers`  | `Sequence[type[ServiceProvider]]` | `()`                 |
| `name`       | `str`                             | `"pylar-test"`       |
| `debug`      | `bool`                            | `True`               |
| `base_path`  | `Path \| None`                    | temp path (no files) |

## HTTP client

`http_client` is an async context manager that bootstraps the app, wires
`httpx.ASGITransport` to the `HttpKernel`, and tears everything down on exit:

```python
from pylar.testing import create_test_app, http_client, TestResponse

async def test_index():
    app = create_test_app(providers=[AppProvider, RouteProvider])
    async with http_client(app) as client:
        response = await client.get("/api/posts")
        TestResponse(response).assert_ok().assert_json_count(3)
```

No uvicorn, no open ports -- the full ASGI stack runs in-process.

## TestResponse assertions

Wrap any `httpx.Response` in `TestResponse` for a fluent assertion chain:

```python
(
    TestResponse(response)
    .assert_status(200)
    .assert_header("content-type", "application/json")
    .assert_json_contains({"title": "Hello pylar"})
)
```

Available assertions: `assert_ok`, `assert_created`, `assert_no_content`,
`assert_redirect`, `assert_unauthorized`, `assert_forbidden`,
`assert_not_found`, `assert_unprocessable`, `assert_header`,
`assert_header_present`, `assert_header_missing`, `assert_text`,
`assert_text_contains`, `assert_json`, `assert_json_contains`,
`assert_json_key`, `assert_json_count`.

## Database testing

Tests use `sqlite+aiosqlite:///:memory:` so no external database is needed.
Two helpers handle schema creation and transactional rollback:

```python
from pylar.testing import in_memory_manager, transactional_session

async def test_user_creation():
    async with in_memory_manager() as mgr:
        async with transactional_session(mgr) as session:
            user = User(email="alice@example.com")
            session.add(user)
            await session.flush()
            assert user.id is not None
        # session is rolled back -- database is clean for the next test
```

For fixture-based setup, use the bundled pytest plugin fixtures
`pylar_db_manager` and `pylar_db_session` instead.

## Model factories

`Factory[ModelT]` generates model instances with default values.
`Sequence` provides unique counters:

```python
from pylar.testing import Factory, Sequence
from app.models import User

class UserFactory(Factory[User]):
    email_seq = Sequence(lambda n: f"user-{n}@example.com")

    @classmethod
    def model_class(cls) -> type[User]:
        return User

    def definition(self) -> dict[str, object]:
        return {"email": self.email_seq.next(), "name": "Test User"}

# In-memory only
user = UserFactory().make(overrides={"name": "Alice"})

# Persisted through the model's Manager
user = await UserFactory().create()

# Bulk
users = await UserFactory().create_many(5)

# Traits for common variants
class PostFactory(Factory[Post]):
    traits = {"published": {"status": "published", "published_at": now()}}

post = PostFactory().with_trait("published").make()
```

## Fake services

Drop-in test doubles record calls for later assertion:

```python
from pylar.testing import FakeMailer, FakeEventBus, FakeNotificationDispatcher

mailer = FakeMailer()
await mailer.send(WelcomeMail(user))
mailer.assert_sent(WelcomeMail, times=1)

bus = FakeEventBus()
await bus.dispatch(UserCreated(user))
bus.assert_dispatched(UserCreated)

notifier = FakeNotificationDispatcher()
await notifier.send(user, InvoicePaid(invoice))
notifier.assert_sent(InvoicePaid, times=1)
```

## Bundled pytest fixtures

The `pylar.testing.plugin` is auto-registered via the `pytest11` entry point:

| Fixture               | Yields                  | Purpose                                      |
|-----------------------|-------------------------|----------------------------------------------|
| `pylar_app_factory`   | `create_test_app`       | Build apps with custom providers              |
| `pylar_test_app`      | `Application`           | Bare app with no providers                    |
| `assert_response`     | `TestResponse` callable | Wrap `httpx.Response` for fluent assertions   |
| `pylar_db_manager`    | `ConnectionManager`     | In-memory SQLite with schema created          |
| `pylar_db_session`    | `None` (ambient)        | Transactional session that rolls back on exit |
