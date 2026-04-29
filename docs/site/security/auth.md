# Authentication & Authorization

Pylar's `auth` module provides user authentication via guards, password hashing, ambient user context, and policy-based authorization -- all async and fully typed.

## The Authenticatable Protocol

Any user model must satisfy the `Authenticatable` protocol:

```python
from pylar.auth import Authenticatable

class User:
    @property
    def auth_identifier(self) -> object:
        return self.id  # opaque id stored in the session

    @property
    def auth_password_hash(self) -> str:
        return self.password_hash
```

The framework never assumes a specific user model. Roles, permissions, and profile fields live on your concrete class.

## Guards

A `Guard` resolves the current user from an incoming request. Pylar ships `SessionGuard`, which reads a user id from the session and resolves it through a callable you provide:

```python
from pylar.auth import Guard, SessionGuard, UserResolver

async def find_user(user_id: object) -> User | None:
    return await User.objects.find(user_id)

guard = SessionGuard(resolver=find_user)

# Register in the container:
container.singleton(Guard, lambda: guard)
```

### Login, Logout & Brute-Force Protection

```python
await guard.login(user)    # writes id to session, regenerates session id
await guard.logout()       # clears the session slot

# In your login controller:
if guard.is_locked_out():
    return JsonResponse({"error": "Too many attempts"}, status_code=429)

guard.record_failed_attempt()  # call when credentials are wrong
guard.remaining_attempts()     # int -- attempts left before lockout
```

`SessionGuard` locks out after 5 failed attempts for 60 seconds by default. Override `max_attempts` and `lockout_seconds` on a subclass to tune.

## Ambient User Context

`AuthMiddleware` resolves the user and binds it to a `ContextVar` for the duration of the request. Downstream code reads it without passing the user through every function signature:

```python
from pylar.auth import current_user, current_user_or_none

user = current_user()           # raises NoCurrentUserError if anonymous
user = current_user_or_none()   # returns None if anonymous
```

In tests, skip the HTTP layer entirely:

```python
from pylar.auth import authenticate_as

with authenticate_as(user):
    assert current_user() is user
```

## AuthMiddleware & RequireAuthMiddleware

```python
from pylar.auth import AuthMiddleware, RequireAuthMiddleware

# AuthMiddleware resolves the user but does NOT reject anonymous requests.
# RequireAuthMiddleware raises 401 if no user is present.
api = router.group(middleware=[AuthMiddleware(guard), RequireAuthMiddleware()])
api.get("/me", UserController.show)
```

## Policies

A `Policy` is a plain class with async methods. Each returns `True` to grant access, `False` to deny. Override only the abilities you allow -- everything else is denied by default:

```python
from pylar.auth import Policy

class PostPolicy(Policy["Post"]):
    async def view(self, user: User, instance: Post) -> bool:
        return True  # anyone can view

    async def update(self, user: User, instance: Post) -> bool:
        return instance.author_id == user.id

    async def delete(self, user: User, instance: Post) -> bool:
        return user.is_admin
```

Built-in abilities: `view_any`, `view`, `create`, `update`, `delete`, `restore`, `force_delete`.

## The Gate

The `Gate` is the central authorization registry. Register policies for model types, then check permissions:

```python
from pylar.auth import Gate

gate = Gate()
gate.policy(Post, PostPolicy())

# Check permission (returns bool):
if await gate.allows(user, "update", post):
    ...

# Or raise AuthorizationError (rendered as 403 by the route compiler):
await gate.authorize(user, "delete", post)
```

### Standalone Abilities

For checks not tied to a model, register a callback:

```python
gate.define("access-admin", admin_check)

await gate.allows(user, "access-admin")
```

## Error Handling

The route compiler catches `AuthorizationError` and renders it as:

```json
{"error": "Not authorized to perform 'delete'"}
```

with HTTP status **403 Forbidden**. No extra wiring needed -- call `gate.authorize()` in your controller and trust the framework.
