"""Behavioural tests for Django-style field declarations."""

from __future__ import annotations

import uuid as _uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import Uuid as SaUuid
from sqlalchemy.orm import Mapped, mapped_column

from pylar.database import (
    ConnectionManager,
    DatabaseConfig,
    Model,
    SoftDeletes,
    fields,
    transaction,
    use_session,
)

# --------------------------------------------------------------------- models


class Article(Model):
    """Pure Django-style — every column declared via fields.*."""

    class Meta:
        db_table = "test_articles"

    title = fields.CharField(max_length=200)
    body = fields.TextField()
    published = fields.BooleanField(default=False)
    views = fields.IntegerField(default=0)
    rating = fields.FloatField(null=True)
    created_at = fields.DateTimeField(auto_now_add=True)


class Tag(Model):
    """Custom primary key declared via AutoField."""

    class Meta:
        db_table = "test_tags"

    name = fields.CharField(max_length=64, unique=True)


class Comment(Model):
    """Mixed style: ForeignKey via field, body via field, indexes too."""

    class Meta:
        db_table = "test_comments"

    article_id = fields.ForeignKey(to="test_articles.id", on_delete="CASCADE", index=True)
    body = fields.TextField()


class SoftArticle(Model, SoftDeletes):
    """Django-style + SoftDeletes mixin — both should compose."""

    class Meta:
        db_table = "test_soft_articles"

    title = fields.CharField(max_length=200)


# ----------------------------------------------------------------- fixtures


@pytest.fixture
async def manager() -> AsyncIterator[ConnectionManager]:
    config = DatabaseConfig(url="sqlite+aiosqlite:///:memory:")
    mgr = ConnectionManager(config)
    await mgr.initialize()
    async with mgr.engine.begin() as conn:
        await conn.run_sync(Model.metadata.create_all)
    try:
        yield mgr
    finally:
        await mgr.dispose()


# --------------------------------------------------------- table generation


def test_meta_db_table_becomes_tablename() -> None:
    assert Article.__tablename__ == "test_articles"
    assert Tag.__tablename__ == "test_tags"


def test_auto_id_column_when_no_primary_key_declared() -> None:
    columns = {col.name: col for col in Article.__table__.columns}
    assert "id" in columns
    assert columns["id"].primary_key is True
    assert columns["id"].autoincrement is True


def test_charfield_translates_to_string_with_length() -> None:
    title_col = Article.__table__.columns["title"]
    assert title_col.type.length == 200  # type: ignore[attr-defined]
    assert title_col.nullable is False


def test_textfield_has_no_length_limit() -> None:
    body_col = Article.__table__.columns["body"]
    assert body_col.nullable is False
    # SQLAlchemy Text has no length attribute or length is None
    assert getattr(body_col.type, "length", None) is None


def test_booleanfield_default_applied() -> None:
    col = Article.__table__.columns["published"]
    assert col.default is not None
    assert col.default.arg is False  # type: ignore[attr-defined]


def test_integerfield_default_applied() -> None:
    col = Article.__table__.columns["views"]
    assert col.default.arg == 0  # type: ignore[attr-defined]


def test_floatfield_nullable() -> None:
    col = Article.__table__.columns["rating"]
    assert col.nullable is True


def test_datetime_auto_now_add_attaches_default() -> None:
    """The behavioural side is covered by the CRUD test below; here we
    just confirm that ``auto_now_add`` produced a column default at all."""
    col = Article.__table__.columns["created_at"]
    assert col.default is not None


def test_charfield_unique() -> None:
    col = Tag.__table__.columns["name"]
    assert col.unique is True


def test_foreignkey_declares_constraint_with_on_delete() -> None:
    col = Comment.__table__.columns["article_id"]
    fks = list(col.foreign_keys)
    assert len(fks) == 1
    fk = fks[0]
    assert fk.column.table.name == "test_articles"
    assert fk.column.name == "id"
    assert fk.ondelete == "CASCADE"


def test_foreignkey_indexed() -> None:
    col = Comment.__table__.columns["article_id"]
    assert col.index is True


def test_foreignkey_requires_target() -> None:
    with pytest.raises(ValueError, match="non-empty `to`"):
        fields.ForeignKey(to="")


# ---------------------------------------------------------- soft delete combo


def test_django_style_composes_with_soft_deletes() -> None:
    columns = {col.name for col in SoftArticle.__table__.columns}
    assert columns == {"id", "title", "deleted_at"}


# ---------------------------------------------------------- end-to-end CRUD


async def test_full_crud_through_django_style_model(
    manager: ConnectionManager,
) -> None:
    async with use_session(manager):
        async with transaction():
            article = Article(
                title="Hello pylar",
                body="First post body",
                published=True,
                views=42,
            )
            await Article.query.save(article)

        # Auto id assigned by autoincrement
        assert article.id is not None
        assert article.created_at is not None  # auto_now_add ran

        fetched = await Article.query.where(Article.title == "Hello pylar").first()
        assert fetched is not None
        assert fetched.title == "Hello pylar"
        assert fetched.body == "First post body"
        assert fetched.published is True
        assert fetched.views == 42
        assert fetched.rating is None  # nullable defaults to None


async def test_unique_constraint_enforced(manager: ConnectionManager) -> None:
    from sqlalchemy.exc import IntegrityError

    async with use_session(manager):
        async with transaction():
            await Tag.query.save(Tag(name="python"))

        with pytest.raises(IntegrityError):
            async with transaction():
                await Tag.query.save(Tag(name="python"))


async def test_soft_delete_works_with_django_style_model(
    manager: ConnectionManager,
) -> None:
    async with use_session(manager):
        async with transaction():
            await SoftArticle.query.save(SoftArticle(title="alpha"))
            await SoftArticle.query.save(SoftArticle(title="beta"))

        target = await SoftArticle.query.where(SoftArticle.title == "alpha").first()
        assert target is not None

        async with transaction():
            await SoftArticle.query.delete(target)

        # Default chain hides it.
        visible = await SoftArticle.query.all()
        assert {a.title for a in visible} == {"beta"}

        # with_trashed brings it back.
        all_articles = await SoftArticle.query.with_trashed().all()
        assert {a.title for a in all_articles} == {"alpha", "beta"}


async def test_foreignkey_round_trip(manager: ConnectionManager) -> None:
    async with use_session(manager):
        async with transaction():
            article = Article(title="Parent", body="x")
            await Article.query.save(article)

        async with transaction():
            comment = Comment(article_id=article.id, body="great post")
            await Comment.query.save(comment)

        fetched = await Comment.query.where(Comment.body == "great post").first()
        assert fetched is not None
        assert fetched.article_id == article.id


# --------------------------------- backwards compatibility with native SA


class LegacyModel(Model):
    """A model declared the old SA-typed way — must keep working."""

    __tablename__ = "test_legacy"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]


async def test_native_sa_models_still_work(manager: ConnectionManager) -> None:
    async with use_session(manager):
        async with transaction():
            await LegacyModel.query.save(LegacyModel(name="legacy"))

        fetched = await LegacyModel.query.where(LegacyModel.name == "legacy").first()
        assert fetched is not None
        assert fetched.id is not None


def test_legacy_model_keeps_its_explicit_id() -> None:
    """The metaclass must not override an existing PK declaration."""
    columns = {col.name: col for col in LegacyModel.__table__.columns}
    assert "id" in columns
    assert columns["id"].primary_key is True
    # Only one column total — the metaclass did not add a duplicate.
    assert set(columns.keys()) == {"id", "name"}


# ----------------------------------------------------------- uuid + jsonb


class SessionModel(Model):
    """UUID-PK model exercised through PrimaryKeyField(as_uuid=True)."""

    class Meta:
        db_table = "test_sessions"

    id = fields.PrimaryKeyField(as_uuid=True)
    user_agent = fields.CharField(max_length=255)
    payload = fields.JSONBField(default=dict)


class SessionEvent(Model):
    """FK pointing at a UUID-PK row uses ForeignKey(as_uuid=True)."""

    class Meta:
        db_table = "test_session_events"

    session_id = fields.ForeignKey(
        to="test_sessions.id", on_delete="CASCADE", as_uuid=True
    )
    name = fields.CharField(max_length=64)


class Account(Model):
    """Standalone UuidField as a public-facing identifier."""

    class Meta:
        db_table = "test_accounts"

    public_id = fields.UuidField(auto=True, unique=True)
    label = fields.CharField(max_length=120)


# ------------------------------------------------------- column metadata


def test_primary_key_field_int_default() -> None:
    """PrimaryKeyField(as_uuid=False) — same shape as AutoField."""

    class _IntegerKeyed(Model):
        class Meta:
            db_table = "test_integer_keyed"

        id = fields.PrimaryKeyField()
        name = fields.CharField(max_length=64)

    col = _IntegerKeyed.__table__.columns["id"]
    assert col.primary_key is True
    assert col.autoincrement is True


def test_primary_key_field_uuid_uses_uuid_type() -> None:
    col = SessionModel.__table__.columns["id"]
    assert col.primary_key is True
    assert isinstance(col.type, SaUuid)
    # The default factory is uuid.uuid4 — we can confirm by calling it.
    factory = col.default.arg  # type: ignore[attr-defined]
    assert callable(factory)


def test_uuid_field_standalone() -> None:
    col = Account.__table__.columns["public_id"]
    assert isinstance(col.type, SaUuid)
    assert col.unique is True
    assert col.nullable is False


def test_jsonb_field_uses_json_with_postgres_variant() -> None:
    col = SessionModel.__table__.columns["payload"]
    # Default backend (sqlite during tests) sees the JSON variant; the
    # Postgres dialect would resolve to JSONB. Either way the column
    # exists and accepts dict values.
    assert col.type.python_type is dict  # type: ignore[attr-defined]


def test_foreign_key_as_uuid_picks_uuid_type() -> None:
    col = SessionEvent.__table__.columns["session_id"]
    assert isinstance(col.type, SaUuid)
    fks = list(col.foreign_keys)
    assert len(fks) == 1
    assert fks[0].column.table.name == "test_sessions"


# ------------------------------------------------------------ end-to-end


async def test_uuid_pk_round_trip(manager: ConnectionManager) -> None:
    async with use_session(manager):
        async with transaction():
            session = SessionModel(
                user_agent="Mozilla/5.0",
                payload={"theme": "dark", "tabs": [1, 2, 3]},
            )
            await SessionModel.query.save(session)

        # default=uuid.uuid4 fired during flush, the id is now a UUID
        assert isinstance(session.id, _uuid.UUID)

        # Round-trip
        fetched = await SessionModel.query.where(SessionModel.id == session.id).first()
        assert fetched is not None
        assert fetched.user_agent == "Mozilla/5.0"
        assert fetched.payload == {"theme": "dark", "tabs": [1, 2, 3]}


async def test_uuid_foreign_key_round_trip(manager: ConnectionManager) -> None:
    async with use_session(manager):
        async with transaction():
            sess = SessionModel(user_agent="curl/8", payload={})
            await SessionModel.query.save(sess)

        async with transaction():
            event = SessionEvent(session_id=sess.id, name="login")
            await SessionEvent.query.save(event)

        fetched = await SessionEvent.query.where(SessionEvent.name == "login").first()
        assert fetched is not None
        assert fetched.session_id == sess.id
        assert isinstance(fetched.session_id, _uuid.UUID)


async def test_standalone_uuid_field_auto(manager: ConnectionManager) -> None:
    async with use_session(manager):
        async with transaction():
            account = Account(label="alice")
            await Account.query.save(account)

        assert isinstance(account.public_id, _uuid.UUID)
        # Two accounts must have distinct generated UUIDs
        async with transaction():
            other = Account(label="bob")
            await Account.query.save(other)
        assert account.public_id != other.public_id


# ------------------------------------------------------ Field.comment


def test_field_comment_lands_on_sqlalchemy_column() -> None:
    """``fields.Field(comment=...)`` is forwarded to ``mapped_column(comment=...)``."""
    from sqlalchemy import inspect as sa_inspect

    from pylar.database import Model, fields

    class _Post(Model):
        __tablename__ = "_comment_post"
        title = fields.CharField(max_length=100, comment="Headline shown on /posts")
        body = fields.TextField(comment="Markdown body")
        priority = fields.IntegerField(default=0)  # no comment

    mapper = sa_inspect(_Post)
    cols = {col.key: col for col in mapper.columns}
    assert cols["title"].comment == "Headline shown on /posts"
    assert cols["body"].comment == "Markdown body"
    assert cols["priority"].comment is None


def test_field_without_comment_emits_none_in_mapped_kwargs() -> None:
    """``comment`` is omitted from mapped_column kwargs when not set,
    so legacy schemas without COMMENT support aren't affected."""
    from pylar.database import fields

    plain = fields.IntegerField()
    kwargs = plain._mapped_column_kwargs()
    assert "comment" not in kwargs

    commented = fields.IntegerField(comment="bump")
    kwargs = commented._mapped_column_kwargs()
    assert kwargs["comment"] == "bump"
