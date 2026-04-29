"""Tests for View.share() and View.with_()."""

from __future__ import annotations

from pathlib import Path

import pytest

from pylar.views import JinjaRenderer, View


@pytest.fixture
def view(tmp_path: Path) -> View:
    (tmp_path / "page.html").write_text("Hello {{ name }}, version {{ version }}")
    return View(JinjaRenderer(tmp_path, autoescape=False))


async def test_share_makes_value_available_in_render(view: View) -> None:
    view.share("version", "1.2.3")
    out = await view.render("page.html", {"name": "Alice"})
    assert out == "Hello Alice, version 1.2.3"


async def test_with_layers_extras_without_mutating_original(view: View) -> None:
    view.share("version", "1.0")
    derived = view.with_({"version": "2.0"})
    a = await derived.render("page.html", {"name": "Carol"})
    b = await view.render("page.html", {"name": "Bob"})
    assert "version 2.0" in a
    assert "version 1.0" in b


async def test_per_call_context_overrides_shared(view: View) -> None:
    view.share("version", "shared")
    out = await view.render("page.html", {"name": "X", "version": "override"})
    assert "version override" in out
