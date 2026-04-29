# Container & Providers

Pylar's IoC container is **typed**. Bindings are keyed by `type[T]`, not strings.
The auto-wiring resolver inspects constructor type hints and refuses to instantiate
anything that lacks them. There are no `**kwargs` in any public API.

## Registering bindings

The container supports four registration methods, each mapping an abstract type
to a concrete implementation or pre-built instance:

```python
from pylar.foundation.container import Container
from pylar.foundation.binding import Scope

container = Container()

# Transient -- fresh instance on every make() call (default)
container.bind(CacheStore, MemoryCacheStore)

# Singleton -- one instance for the lifetime of the container
container.singleton(Mailer, SmtpMailer)

# Scoped -- one instance per active scope context (e.g. per request)
container.scoped(UnitOfWork, SqlUnitOfWork)

# Pre-built instance -- registered as a singleton immediately
container.instance(AppConfig, config)
```

!!! info "Concrete can be a class or a zero-arg factory"
    The `concrete` argument accepts either a class (auto-wired via constructor
    inspection) or a zero-argument callable that returns the instance directly.

## Resolving instances

Call `container.make(SomeType)` to get a fully-constructed instance. The
container walks the constructor's type hints and recursively resolves each
dependency:

```python
class UserRepository:
    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

class UserService:
    def __init__(self, repo: UserRepository) -> None:
        self.repo = repo

container.singleton(DatabaseManager, DatabaseManager)
user_service = container.make(UserService)  # (1)!
```

1. `UserService` has no explicit binding, so the container auto-resolves it as
   transient. `UserRepository` is also auto-resolved, and `DatabaseManager` is
   pulled from the singleton cache.

!!! warning "Auto-resolution rules"
    - Classes with no binding are built on the fly (always transient).
    - Protocols and abstract classes without a binding raise `BindingError`.
    - Circular dependencies raise `CircularDependencyError`.
    - Constructor parameters with a default value **and** no container binding
      are left to the constructor default -- the container does not try to
      instantiate `str` or `int`.

## Scoped lifetimes

Open a scope with `container.scope()`. Any `SCOPED` binding resolved inside
the block is cached for its duration and discarded on exit:

```python
container.scoped(Session, DbSession)

with container.scope():
    s1 = container.make(Session)
    s2 = container.make(Session)
    assert s1 is s2  # same instance within the scope

s3 = container.make(Session)  # new scope, new instance
```

The `RoutesCompiler` opens a scope per HTTP request automatically, so scoped
bindings work as per-request singletons without any manual setup.

## Calling arbitrary functions

`Container.call()` invokes any callable with its parameters resolved from the
container. Two override mechanisms let the caller inject runtime values:

```python
async def create_user(
    request: Request,
    repo: UserRepository,
    user_id: int,
) -> Response:
    ...

response = container.call(
    create_user,
    overrides={Request: current_request},  # matched by type
    params={"user_id": 42},                # matched by parameter name
)
```

Resolution order per parameter: `params` (by name) > `overrides` (by type) >
container auto-resolution.

## Tagging

Group related bindings under a string tag for bulk resolution:

```python
container.singleton(UserPolicy, UserPolicy)
container.singleton(PostPolicy, PostPolicy)
container.tag([UserPolicy, PostPolicy], "policies")

all_policies = container.tagged("policies")  # list of resolved instances
```

## Service providers

A `ServiceProvider` is the only sanctioned extension point. It has three
lifecycle hooks:

| Hook | Sync/Async | Purpose |
|---|---|---|
| `register(container)` | sync | Bind types. No I/O, no cross-provider lookups. |
| `boot(container)` | async | Side effects: open pools, attach listeners, register routes. |
| `shutdown(container)` | async | Release resources. Runs in reverse registration order. |

```python
from pylar.foundation.provider import ServiceProvider
from pylar.foundation.container import Container

class MailServiceProvider(ServiceProvider):
    def register(self, container: Container) -> None:
        container.singleton(Mailer, SmtpMailer)
        container.bind(MailTransport, SmtpTransport)

    async def boot(self, container: Container) -> None:
        mailer = container.make(Mailer)
        await mailer.verify_connection()

    async def shutdown(self, container: Container) -> None:
        mailer = container.make(Mailer)
        await mailer.close()
```

Register providers in your `AppConfig`:

```python
from pylar.foundation.application import AppConfig

config = AppConfig(
    name="myapp",
    providers=(
        MailServiceProvider,
        DatabaseServiceProvider,
        AuthServiceProvider,
    ),
)
```

The `Application` instantiates every provider, calls `register` on all of them
first, then `boot` on all of them second. This two-phase lifecycle means any
provider can reference bindings from any other provider during `boot`,
regardless of registration order.
