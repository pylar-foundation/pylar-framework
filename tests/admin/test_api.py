"""Integration tests for the admin API controller."""

from __future__ import annotations

import pytest
from pylar_admin.config import AdminConfig
from pylar_admin.controllers.api import AdminApiController
from pylar_admin.registry import AdminRegistry

from tests.admin.conftest import Article, Tag


@pytest.fixture
def api(registry: AdminRegistry, admin_config: AdminConfig) -> AdminApiController:
    registry.register(Article)
    registry.register(Tag)
    return AdminApiController(registry, admin_config)


class TestAdminApi:
    async def test_models_index(
        self, api: AdminApiController, db_session: None
    ) -> None:

        # Direct controller call — build a minimal Request.
        from pylar.http import Request

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/admin/api/models",
            "query_string": b"",
            "headers": [],
        }
        request = Request(scope)
        response = await api.models_index(request)
        assert response.status_code == 200
        import json

        body = json.loads(response.body)
        slugs = [m["slug"] for m in body["models"]]
        assert "articles" in slugs
        assert "tags" in slugs

    async def test_model_schema(
        self, api: AdminApiController, db_session: None
    ) -> None:
        from pylar.http import Request

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/admin/api/models/articles/schema",
            "query_string": b"",
            "headers": [],
        }
        request = Request(scope)
        response = await api.model_schema(request, slug="articles")
        assert response.status_code == 200
        import json

        body = json.loads(response.body)
        assert body["slug"] == "articles"
        assert any(f["name"] == "title" for f in body["fields"])

    async def test_model_schema_not_found(
        self, api: AdminApiController, db_session: None
    ) -> None:
        from pylar.http import Request

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/admin/api/models/nope/schema",
            "query_string": b"",
            "headers": [],
        }
        request = Request(scope)
        response = await api.model_schema(request, slug="nope")
        assert response.status_code == 404
