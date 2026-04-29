"""Tests for model serialization and deserialization."""

from datetime import UTC, datetime

from pylar_admin.serializer import _to_json_value, deserialize_form_data

from tests.admin.conftest import Article, Tag


class TestToJsonValue:
    def test_none(self) -> None:
        assert _to_json_value(None) is None

    def test_string(self) -> None:
        assert _to_json_value("hello") == "hello"

    def test_int(self) -> None:
        assert _to_json_value(42) == 42

    def test_bool(self) -> None:
        assert _to_json_value(True) is True

    def test_datetime(self) -> None:
        dt = datetime(2026, 1, 15, 12, 30, 0, tzinfo=UTC)
        result = _to_json_value(dt)
        assert "2026-01-15" in result
        assert isinstance(result, str)

    def test_bytes_excluded(self) -> None:
        assert _to_json_value(b"binary") is None

    def test_dict(self) -> None:
        result = _to_json_value({"key": 42})
        assert result == {"key": 42}

    def test_list(self) -> None:
        result = _to_json_value([1, "two", None])
        assert result == [1, "two", None]


class TestDeserializeFormData:
    """Tests for deserialize_form_data — the function that parses raw
    JSON/form input into typed values for model attribute assignment.
    """

    def test_basic_fields(self) -> None:
        """Normal fields are coerced and returned."""
        result = deserialize_form_data(
            Tag, {"name": "python"}
        )
        assert result == {"name": "python"}

    def test_skips_primary_key(self) -> None:
        """PK column is never overwritten from input."""
        result = deserialize_form_data(
            Tag, {"id": 42, "name": "python"}
        )
        assert "id" not in result
        assert result["name"] == "python"

    def test_skips_created_at(self) -> None:
        """created_at is auto-managed and must not be set from input."""
        result = deserialize_form_data(
            Article, {"title": "Test", "created_at": "2026-01-01T00:00:00"}
        )
        assert "created_at" not in result

    def test_skips_updated_at(self) -> None:
        """updated_at is auto-managed and must not be set from input."""
        result = deserialize_form_data(
            Article, {"title": "Test", "updated_at": "2026-01-01T00:00:00"}
        )
        assert "updated_at" not in result

    def test_skips_empty_created_at(self) -> None:
        """Empty string for timestamps must not overwrite the ORM default."""
        result = deserialize_form_data(
            Article, {"title": "Test", "created_at": "", "updated_at": ""}
        )
        assert "created_at" not in result
        assert "updated_at" not in result

    def test_skips_null_timestamps(self) -> None:
        """None for timestamps must not overwrite the ORM default."""
        result = deserialize_form_data(
            Article, {"title": "Test", "created_at": None, "updated_at": None}
        )
        assert "created_at" not in result
        assert "updated_at" not in result

    def test_respects_readonly_fields(self) -> None:
        """Fields listed in readonly are skipped."""
        result = deserialize_form_data(
            Article,
            {"title": "Test", "body": "Content"},
            readonly=("body",),
        )
        assert "title" in result
        assert "body" not in result

    def test_respects_allowed_fields(self) -> None:
        """Only fields listed in `fields` are processed."""
        result = deserialize_form_data(
            Article,
            {"title": "Test", "body": "Content", "published": True},
            fields=("title",),
        )
        assert result == {"title": "Test"}

    def test_boolean_coercion(self) -> None:
        """Boolean values are coerced from strings."""
        result = deserialize_form_data(
            Article, {"published": "true"}
        )
        assert result["published"] is True

        result2 = deserialize_form_data(
            Article, {"published": "false"}
        )
        assert result2["published"] is False

    def test_skips_empty_value_with_default(self) -> None:
        """Empty string for a column with a default lets the ORM fill it."""
        result = deserialize_form_data(
            Article, {"published": ""}
        )
        # published has default=False, empty string should be skipped
        assert "published" not in result

    def test_sqlalchemy_column_no_bool_error(self) -> None:
        """Regression: accessing Column objects must not trigger __bool__.

        Previously used `if col := prop.columns[0]` which called
        Column.__bool__() → TypeError. This test ensures the fix holds.
        """
        # If this raises TypeError("Boolean value of this clause is not
        # defined"), the walrus operator regression has returned.
        result = deserialize_form_data(
            Article,
            {"title": "Hello", "body": "World", "published": True},
        )
        assert result["title"] == "Hello"
        assert result["body"] == "World"
        assert result["published"] is True
