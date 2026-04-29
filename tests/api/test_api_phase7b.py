"""Tests for the OpenAPI generator and docs endpoints (ADR-0007 phase 7b).

Covers:

* ``generate_openapi`` walks Router + handler signatures and produces
  a well-formed OpenAPI 3.1 dict: path params, DTO request bodies,
  pydantic return schemas, standard error envelopes.
* The ``ApiServiceProvider`` mounts ``/openapi.json``, ``/docs``, and
  ``/redoc`` when ``ApiDocsConfig.enabled`` is true.
* The ``api:docs`` console command prints or writes the spec.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from pydantic import BaseModel

from pylar.api import (
    ApiDocsConfig,
    ApiErrorMiddleware,
    ApiServiceProvider,
    Page,
    generate_openapi,
)
from pylar.api.commands import ApiDocsCommand, _ApiDocsInput
from pylar.console.output import Output
from pylar.foundation import Container, ServiceProvider
from pylar.routing import Router
from pylar.testing import create_test_app, http_client
from pylar.validation import RequestDTO

# ----------------------------------------------------------- test fixtures


class _CreatePost(RequestDTO):
    title: str
    body: str


class _PostResource(BaseModel):
    id: int
    title: str


async def _index() -> list[_PostResource]:
    """List every post."""
    return []


async def _show(post_id: int) -> _PostResource:
    """Return a single post."""
    return _PostResource(id=post_id, title="x")


async def _store(body: _CreatePost) -> _PostResource:
    """Create a post."""
    return _PostResource(id=1, title=body.title)


async def _paginated() -> Page[_PostResource]:
    """Return a paginated list of posts.

    Extra body lines that should flow into the OpenAPI description
    field as Markdown.
    """
    from pylar.database.paginator import Paginator

    return Page.from_paginator(
        Paginator(items=[], total=0, per_page=10, current_page=1, path="/x"),
        [],
    )


def _build_router() -> Router:
    router = Router()
    router.get("/posts", _index, name="posts.index")
    router.get("/posts/{post_id:int}", _show, name="posts.show")
    router.post(
        "/posts", _store, middleware=[ApiErrorMiddleware], name="posts.store"
    )
    router.get("/posts/paginated", _paginated, name="posts.paginated")
    return router


# --------------------------------------------------- generator unit tests


def test_openapi_document_has_info_and_openapi_version() -> None:
    spec = generate_openapi(_build_router(), title="Demo", version="1.2.3")
    assert spec["openapi"] == "3.1.0"
    assert spec["info"] == {"title": "Demo", "version": "1.2.3"}


def test_openapi_servers_block_is_populated_when_provided() -> None:
    spec = generate_openapi(
        _build_router(),
        servers=("https://api.example.com", "https://staging.example.com"),
    )
    assert spec["servers"] == [
        {"url": "https://api.example.com"},
        {"url": "https://staging.example.com"},
    ]


def test_openapi_summary_and_description_come_from_docstring() -> None:
    spec = generate_openapi(_build_router())
    op = spec["paths"]["/posts/paginated"]["get"]
    assert op["summary"].startswith("Return a paginated")
    # Body after the summary line lands in description.
    assert "Extra body lines" in op.get("description", "")


def test_openapi_list_endpoint_schema_references_resource() -> None:
    spec = generate_openapi(_build_router())
    op = spec["paths"]["/posts"]["get"]
    schema = op["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema["type"] == "array"
    assert schema["items"] == {"$ref": "#/components/schemas/_PostResource"}
    assert "_PostResource" in spec["components"]["schemas"]


def test_openapi_path_param_is_typed_integer() -> None:
    spec = generate_openapi(_build_router())
    op = spec["paths"]["/posts/{post_id}"]["get"]
    params = {p["name"]: p for p in op["parameters"]}
    assert params["post_id"]["in"] == "path"
    assert params["post_id"]["required"] is True
    assert params["post_id"]["schema"] == {"type": "integer"}


def test_openapi_post_has_request_body_from_dto() -> None:
    spec = generate_openapi(_build_router())
    op = spec["paths"]["/posts"]["post"]
    body = op["requestBody"]
    assert body["required"] is True
    ref = body["content"]["application/json"]["schema"]["$ref"]
    assert ref.endswith("/_CreatePost")
    assert "_CreatePost" in spec["components"]["schemas"]


def test_openapi_standard_error_responses_present() -> None:
    spec = generate_openapi(_build_router())
    op = spec["paths"]["/posts"]["get"]
    assert "422" in op["responses"]
    assert "403" in op["responses"]


def test_openapi_page_return_registers_envelope_schema() -> None:
    spec = generate_openapi(_build_router())
    op = spec["paths"]["/posts/paginated"]["get"]
    schema = op["responses"]["200"]["content"]["application/json"]["schema"]
    # The Page[T] return registers as a ref to a concrete Page schema.
    assert schema["$ref"].startswith("#/components/schemas/Page")


# ---------------------------------------------- provider mounts endpoints


class _DocsProvider(ServiceProvider):
    def register(self, container: Container) -> None:
        container.singleton(Router, _build_router)


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = create_test_app(providers=[_DocsProvider, ApiServiceProvider])
    async with http_client(app) as c:
        yield c


async def test_openapi_json_endpoint_returns_spec(
    client: httpx.AsyncClient,
) -> None:
    r = await client.get("/openapi.json")
    assert r.status_code == 200
    assert r.json()["openapi"] == "3.1.0"
    assert "/posts" in r.json()["paths"]


async def test_swagger_ui_endpoint_serves_html(
    client: httpx.AsyncClient,
) -> None:
    r = await client.get("/docs")
    assert r.status_code == 200
    assert "swagger-ui" in r.text


async def test_redoc_endpoint_serves_html(client: httpx.AsyncClient) -> None:
    r = await client.get("/redoc")
    assert r.status_code == 200
    assert "redoc" in r.text.lower()


# ------------------------------------------------- disabled docs toggle


class _DisabledDocsProvider(ServiceProvider):
    def register(self, container: Container) -> None:
        container.singleton(Router, _build_router)
        container.instance(ApiDocsConfig, ApiDocsConfig(enabled=False))


async def test_disabled_docs_config_hides_endpoints() -> None:
    app = create_test_app(
        providers=[_DisabledDocsProvider, ApiServiceProvider],
    )
    async with http_client(app) as c:
        r = await c.get("/openapi.json")
        assert r.status_code == 404


# ---------------------------------------------------- api:docs command


async def test_api_docs_command_prints_spec_to_stdout() -> None:
    from io import StringIO

    router = _build_router()
    buf = StringIO()
    cmd = ApiDocsCommand(router, ApiDocsConfig(), Output(buf, colour=False))
    code = await cmd.handle(_ApiDocsInput())
    assert code == 0
    parsed = json.loads(buf.getvalue())
    assert parsed["openapi"] == "3.1.0"


async def test_api_docs_command_writes_file(tmp_path: Path) -> None:
    from io import StringIO

    router = _build_router()
    buf = StringIO()
    cmd = ApiDocsCommand(router, ApiDocsConfig(), Output(buf, colour=False))
    target = tmp_path / "openapi.json"
    code = await cmd.handle(_ApiDocsInput(output=str(target)))
    assert code == 0
    assert target.is_file()
    parsed = json.loads(target.read_text())
    assert parsed["openapi"] == "3.1.0"
