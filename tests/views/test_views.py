"""Behavioural tests for the views layer."""

from __future__ import annotations

from pathlib import Path

import pytest

from pylar.http import HtmlResponse
from pylar.views import (
    JinjaRenderer,
    TemplateNotFoundError,
    View,
    ViewRenderer,
)


@pytest.fixture
def templates(tmp_path: Path) -> Path:
    root = tmp_path / "views"
    root.mkdir()
    (root / "home.html").write_text(
        "<h1>Hello, {{ name }}!</h1>", encoding="utf-8"
    )
    (root / "raw.html").write_text("Raw: {{ payload }}", encoding="utf-8")
    return root


@pytest.fixture
def renderer(templates: Path) -> JinjaRenderer:
    return JinjaRenderer(templates)


async def test_render_substitutes_context(renderer: JinjaRenderer) -> None:
    body = await renderer.render("home.html", {"name": "Alice"})
    assert body == "<h1>Hello, Alice!</h1>"


async def test_autoescape_protects_html_files(renderer: JinjaRenderer) -> None:
    body = await renderer.render("raw.html", {"payload": "<script>x</script>"})
    assert "<script>" not in body
    assert "&lt;script&gt;" in body


async def test_autoescape_disabled_via_constructor(templates: Path) -> None:
    renderer = JinjaRenderer(templates, autoescape=False)
    body = await renderer.render("raw.html", {"payload": "<b>bold</b>"})
    assert "<b>bold</b>" in body


async def test_missing_template_raises(renderer: JinjaRenderer) -> None:
    with pytest.raises(TemplateNotFoundError, match=r"missing\.html"):
        await renderer.render("missing.html", {})


async def test_view_make_returns_html_response(renderer: JinjaRenderer) -> None:
    view = View(renderer)
    response = await view.make("home.html", {"name": "Bob"}, status=201)
    assert isinstance(response, HtmlResponse)
    assert response.status_code == 201
    assert response.body == b"<h1>Hello, Bob!</h1>"


async def test_view_render_returns_string(renderer: JinjaRenderer) -> None:
    view = View(renderer)
    body = await view.render("home.html", {"name": "Carol"})
    assert isinstance(body, str)
    assert "Carol" in body


def test_jinja_renderer_satisfies_protocol(renderer: JinjaRenderer) -> None:
    assert isinstance(renderer, ViewRenderer)
