"""Behavioural tests for the ``make:*`` generators."""

from __future__ import annotations

import ast
from io import StringIO
from pathlib import Path

import pytest

from pylar.console.make import (
    ALL_MAKE_COMMANDS,
    SPECS,
    Generator,
    InvalidNameError,
    MakeNameInput,
    TargetExistsError,
    to_kebab,
    to_snake,
    validate_pascal,
)
from pylar.console.make.commands import MakeCommand
from pylar.console.output import Output
from pylar.foundation import AppConfig, Application

# ----------------------------------------------------------------- naming


@pytest.mark.parametrize("name,expected", [
    ("User", "user"),
    ("UserProfile", "user_profile"),
    ("HTTPClient", "http_client"),
    ("APIRequest", "api_request"),
    ("X", "x"),
])
def test_to_snake(name: str, expected: str) -> None:
    assert to_snake(name) == expected


def test_to_kebab() -> None:
    assert to_kebab("UserProfile") == "user-profile"
    assert to_kebab("HTTPClient") == "http-client"


@pytest.mark.parametrize("name", ["User", "UserProfile", "X", "ABC123"])
def test_validate_pascal_accepts_valid(name: str) -> None:
    assert validate_pascal(name) == name


@pytest.mark.parametrize("name", ["user", "userProfile", "_User", "user-profile", ""])
def test_validate_pascal_rejects_invalid(name: str) -> None:
    with pytest.raises(InvalidNameError):
        validate_pascal(name)


# --------------------------------------------------------------- generator


def test_generator_writes_target_under_base_path(tmp_path: Path) -> None:
    gen = Generator(SPECS["model"], tmp_path, "User")
    target = gen.write()
    assert target == tmp_path / "app" / "models" / "user.py"
    assert target.is_file()


def test_generator_renders_substitutions(tmp_path: Path) -> None:
    gen = Generator(SPECS["model"], tmp_path, "UserProfile")
    target = gen.write()
    body = target.read_text()
    assert "class UserProfile(Model)" in body
    assert '__tablename__ = "user_profiles"' in body


def test_generator_refuses_overwrite_by_default(tmp_path: Path) -> None:
    Generator(SPECS["model"], tmp_path, "User").write()
    with pytest.raises(TargetExistsError):
        Generator(SPECS["model"], tmp_path, "User").write()


def test_generator_force_overwrites(tmp_path: Path) -> None:
    target = Generator(SPECS["model"], tmp_path, "User").write()
    target.write_text("# stale\n", encoding="utf-8")
    Generator(SPECS["model"], tmp_path, "User", force=True).write()
    assert "stale" not in target.read_text()
    assert "class User(Model)" in target.read_text()


def test_generator_creates_missing_parent_directories(tmp_path: Path) -> None:
    Generator(SPECS["controller"], tmp_path, "Posts").write()
    assert (tmp_path / "app" / "http" / "controllers" / "posts.py").is_file()


# --------------------------------------------------------------- commands


@pytest.fixture
def app(tmp_path: Path) -> Application:
    return Application(
        base_path=tmp_path,
        config=AppConfig(name="make-test", debug=True, providers=()),
    )


@pytest.mark.parametrize("command_cls", ALL_MAKE_COMMANDS)
async def test_every_make_command_writes_a_parseable_file(
    command_cls: type[MakeCommand],
    app: Application,
) -> None:
    buf = StringIO()
    command = command_cls(app, Output(buf, colour=False))
    code = await command.handle(MakeNameInput(name="Sample"))
    assert code == 0

    assert "Created" in buf.getvalue()

    target = command.spec.target.replace("${snake_name}", "sample")
    file_path = app.base_path / target
    assert file_path.is_file()

    # The generated source must be valid Python.
    ast.parse(file_path.read_text(encoding="utf-8"))


async def test_make_command_reports_target_exists(app: Application) -> None:
    from pylar.console.make import MakeModelCommand

    buf = StringIO()
    cmd = MakeModelCommand(app, Output(buf, colour=False))
    assert await cmd.handle(MakeNameInput(name="Twice")) == 0
    assert await cmd.handle(MakeNameInput(name="Twice")) == 1
    assert "already exists" in buf.getvalue()


async def test_make_command_force_overrides(app: Application) -> None:
    from pylar.console.make import MakeModelCommand

    cmd = MakeModelCommand(app, Output(StringIO(), colour=False))
    await cmd.handle(MakeNameInput(name="Forceful"))
    assert (
        await cmd.handle(MakeNameInput(name="Forceful", force=True)) == 0
    )


async def test_make_command_rejects_lowercase_name(app: Application) -> None:
    from pylar.console.make import MakeModelCommand

    buf = StringIO()
    cmd = MakeModelCommand(app, Output(buf, colour=False))
    code = await cmd.handle(MakeNameInput(name="badName"))
    assert code == 2
    assert "PascalCase" in buf.getvalue()


def test_specs_cover_every_command_class() -> None:
    for command_cls in ALL_MAKE_COMMANDS:
        assert command_cls.spec in SPECS.values()
