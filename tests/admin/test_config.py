"""Tests for AdminConfig and ModelAdmin."""

from pylar_admin.config import AdminConfig, ModelAdmin


class TestAdminConfig:
    def test_defaults(self) -> None:
        config = AdminConfig()
        assert config.enabled is True
        assert config.prefix == "/admin"
        assert config.site_title == "Pylar Admin"
        assert config.per_page == 25
        assert config.require_auth is True

    def test_custom_values(self) -> None:
        config = AdminConfig(
            enabled=False, prefix="/panel", site_title="My App", per_page=50
        )
        assert config.enabled is False
        assert config.prefix == "/panel"
        assert config.per_page == 50


class TestModelAdmin:
    def test_defaults(self) -> None:
        admin = ModelAdmin()
        assert admin.list_display is None
        assert admin.list_filter == ()
        assert admin.search_fields == ()
        assert admin.form_fields is None
        assert admin.readonly_fields == ()
        assert admin.ordering == ()
        assert admin.per_page is None

    def test_custom_config(self) -> None:
        admin = ModelAdmin(
            list_display=("title", "published"),
            search_fields=("title",),
            ordering=("-created_at",),
            per_page=15,
        )
        assert admin.list_display == ("title", "published")
        assert admin.search_fields == ("title",)
        assert admin.per_page == 15
