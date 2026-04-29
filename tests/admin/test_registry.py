"""Tests for AdminRegistry."""

import pytest
from pylar_admin.config import ModelAdmin
from pylar_admin.exceptions import AdminConfigError, ModelNotRegisteredError
from pylar_admin.registry import AdminRegistry

from tests.admin.conftest import Article, Tag


class TestAdminRegistry:
    def test_register_auto_config(self, registry: AdminRegistry) -> None:
        registry.register(Article)
        reg = registry.get_for_model(Article)
        assert reg.model is Article
        assert reg.slug == "articles"
        assert reg.label == "Article"

    def test_register_with_custom_config(self, registry: AdminRegistry) -> None:
        custom = ModelAdmin(
            list_display=("name",),
            search_fields=("name",),
        )
        registry.register(Tag, custom)
        reg = registry.get_for_model(Tag)
        assert reg.config.list_display == ("name",)

    def test_duplicate_registration_raises(self, registry: AdminRegistry) -> None:
        registry.register(Article)
        with pytest.raises(AdminConfigError, match="already registered"):
            registry.register(Article)

    def test_get_by_slug(self, registry: AdminRegistry) -> None:
        registry.register(Article)
        reg = registry.get("articles")
        assert reg.model is Article

    def test_get_unknown_slug_raises(self, registry: AdminRegistry) -> None:
        with pytest.raises(ModelNotRegisteredError):
            registry.get("nonexistent")

    def test_unregister(self, registry: AdminRegistry) -> None:
        registry.register(Article)
        registry.unregister(Article)
        assert Article not in registry.registered_models()

    def test_registered_models(self, registry: AdminRegistry) -> None:
        registry.register(Article)
        registry.register(Tag)
        models = registry.registered_models()
        assert Article in models
        assert Tag in models

    def test_model_schema(self, registry: AdminRegistry) -> None:
        registry.register(Article)
        schema = registry.model_schema("articles")
        assert schema["slug"] == "articles"
        assert schema["label"] == "Article"
        field_names = [f["name"] for f in schema["fields"]]
        assert "id" in field_names
        assert "title" in field_names
        assert "published" in field_names

    def test_auto_config_excludes_pk_from_form(self, registry: AdminRegistry) -> None:
        registry.register(Article)
        reg = registry.get_for_model(Article)
        assert reg.config.form_fields is not None
        assert "id" not in reg.config.form_fields
