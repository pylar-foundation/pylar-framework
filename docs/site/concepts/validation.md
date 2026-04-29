# Validation

Pylar validates incoming request data through Pydantic-based DTOs that are
auto-resolved from handler signatures. Invalid input is rendered as a
structured 422 JSON response with no boilerplate in the handler.

## Defining a RequestDTO

Subclass `RequestDTO` and declare typed fields. The base class configures
strict Pydantic defaults: unknown fields are rejected, instances are frozen,
and string values are stripped of whitespace.

```python
from pylar.validation.dto import RequestDTO
from pydantic import Field, field_validator

class CreatePostDTO(RequestDTO):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1)
    published: bool = False

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("title must not be blank")
        return v
```

## Auto-resolution in route handlers

Type-hint a handler parameter as a `RequestDTO` subclass and pylar parses the
request body into it automatically. No decorators, no manual parsing:

```python
from pylar.http.request import Request
from pylar.http.response import JsonResponse

async def create_post(request: Request, dto: CreatePostDTO) -> JsonResponse:
    post = Post(title=dto.title, body=dto.body, published=dto.published)
    await Post.query.save(post)
    return JsonResponse({"id": post.id}, status_code=201)

router.post("/posts", create_post)
```

The data source is chosen by HTTP method:

| Method | Source |
|---|---|
| `GET`, `DELETE`, `HEAD`, `OPTIONS` | `request.query_params` |
| `POST`, `PUT`, `PATCH` with `application/json` | JSON body |
| `POST`, `PUT`, `PATCH` with form content type | `request.form()` |

## 422 error format

When validation fails, the `RoutesCompiler` catches the `ValidationError` and
returns a 422 response. The error body is a JSON object with an `errors` array
matching Pydantic's structure:

```json
{
  "errors": [
    {
      "loc": ["title"],
      "msg": "String should have at least 1 character",
      "type": "string_too_short"
    },
    {
      "loc": ["body"],
      "msg": "Field required",
      "type": "missing"
    }
  ]
}
```

Each error includes `loc` (field path), `msg` (human-readable message), and
`type` (machine-readable error code).

## HeaderDTO and CookieDTO

Validate headers and cookies with dedicated base classes:

```python
from pylar.validation.dto import HeaderDTO, CookieDTO
from pydantic import Field

class WebhookHeaders(HeaderDTO):
    signature: str = Field(alias="x-signature")
    delivery_id: str = Field(alias="x-delivery-id")

class AuthCookies(CookieDTO):
    session_token: str = Field(alias="session")

async def webhook(
    request: Request,
    headers: WebhookHeaders,  # (1)!
) -> JsonResponse:
    verify(headers.signature, await request.body())
    return JsonResponse({"ok": True})
```

1. `HeaderDTO` parameters are resolved from `request.headers` (case-insensitive).
   `CookieDTO` parameters are resolved from `request.cookies`. Unknown
   headers/cookies are silently ignored.

## File uploads

Type-hint a parameter as `UploadFile` and pylar pulls it from `request.form()`:

```python
from pylar.validation.upload import UploadFile

async def upload_avatar(request: Request, avatar: UploadFile) -> JsonResponse:
    contents = await avatar.read()
    # ... store the file
    return JsonResponse({"filename": avatar.filename})
```

A missing or non-file field raises a 422 with `type: "upload.missing"`.

## Combining DTOs with path parameters

DTOs and path parameters work together. The framework merges them into a
single `params` dict before calling the handler:

```python
class UpdatePostDTO(RequestDTO):
    title: str = Field(min_length=1, max_length=200)
    body: str

async def update_post(
    request: Request,
    post_id: int,           # from path
    dto: UpdatePostDTO,     # from JSON body
) -> JsonResponse:
    post = await Post.query.get(post_id)
    post.title = dto.title
    post.body = dto.body
    await Post.query.save(post)
    return JsonResponse({"id": post.id})

router.put("/posts/{post_id:int}", update_post)
```

## Custom validation rules

Since `RequestDTO` is a standard Pydantic `BaseModel`, you have access to all
of Pydantic's validation features:

```python
from pydantic import field_validator, model_validator

class RegisterDTO(RequestDTO):
    email: str
    password: str = Field(min_length=8)
    password_confirmation: str

    @field_validator("email")
    @classmethod
    def valid_email(cls, v: str) -> str:
        if "@" not in v:
            raise ValueError("invalid email address")
        return v.lower()

    @model_validator(mode="after")
    def passwords_match(self) -> "RegisterDTO":
        if self.password != self.password_confirmation:
            raise ValueError("passwords do not match")
        return self
```

!!! tip "Relaxing defaults"
    The base `RequestDTO` sets `extra="forbid"` and `frozen=True`. Override
    `model_config` on your subclass if you need to accept extra fields or
    allow mutation after construction.
