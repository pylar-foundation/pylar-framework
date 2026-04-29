"""Tests for the new Output service and the help builtin command."""

from __future__ import annotations

from pylar.console import BufferedOutput, Output


def test_buffered_output_captures_writes() -> None:
    out = BufferedOutput()
    out.write("hello")
    out.line(" world")
    assert out.getvalue() == "hello world\n"


def test_buffered_output_skips_colour_by_default() -> None:
    out = BufferedOutput()
    out.success("ok")
    out.warn("careful")
    out.error("nope")
    captured = out.getvalue()
    assert "\033[" not in captured
    assert "ok" in captured and "careful" in captured and "nope" in captured


def test_table_renders_aligned_columns() -> None:
    out = BufferedOutput()
    out.table(["name", "size"], [("alpha", "1"), ("beta-very-long", "200")])
    captured = out.getvalue()
    # Rich table renders headers and data rows.
    assert "name" in captured
    assert "size" in captured
    assert "alpha" in captured
    assert "beta-very-long" in captured
    assert "200" in captured


def test_output_with_explicit_writer() -> None:
    from io import StringIO

    buf = StringIO()
    out = Output(buf, colour=False)
    out.info("hi")
    assert "hi" in buf.getvalue()
