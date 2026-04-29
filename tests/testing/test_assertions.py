"""Tests for the :class:`TestResponse` HTTP assertion DSL."""

from __future__ import annotations

import json

import httpx
import pytest

from pylar.testing import TestResponse


def _response(
    *,
    status: int = 200,
    headers: dict[str, str] | None = None,
    body: str | bytes | None = None,
    json_body: object = None,
) -> httpx.Response:
    if json_body is not None:
        body = json.dumps(json_body)
        headers = {**(headers or {}), "content-type": "application/json"}
    request = httpx.Request("GET", "http://test/")
    return httpx.Response(
        status_code=status,
        headers=headers or {},
        content=body if isinstance(body, bytes) else (body or "").encode(),
        request=request,
    )


# ----------------------------------------------------------- status helpers


def test_assert_status_passes_for_match() -> None:
    TestResponse(_response(status=201)).assert_status(201)


def test_assert_status_raises_on_mismatch() -> None:
    with pytest.raises(AssertionError, match="Expected HTTP 200"):
        TestResponse(_response(status=500)).assert_status(200)


def test_assert_ok_shortcut() -> None:
    TestResponse(_response(status=200)).assert_ok()
    with pytest.raises(AssertionError):
        TestResponse(_response(status=404)).assert_ok()


def test_assert_created_no_content_redirect() -> None:
    TestResponse(_response(status=201)).assert_created()
    TestResponse(_response(status=204)).assert_no_content()
    TestResponse(_response(status=302, headers={"location": "/x"})).assert_redirect("/x")


def test_assert_redirect_wrong_location() -> None:
    with pytest.raises(AssertionError, match="redirect to"):
        TestResponse(
            _response(status=302, headers={"location": "/x"})
        ).assert_redirect("/y")


def test_assert_unauthorized_forbidden_not_found_unprocessable() -> None:
    TestResponse(_response(status=401)).assert_unauthorized()
    TestResponse(_response(status=403)).assert_forbidden()
    TestResponse(_response(status=404)).assert_not_found()
    TestResponse(_response(status=422)).assert_unprocessable()


# ----------------------------------------------------------- header helpers


def test_assert_header_value_match() -> None:
    TestResponse(
        _response(headers={"x-trace": "abc"})
    ).assert_header("x-trace", "abc")


def test_assert_header_value_mismatch() -> None:
    with pytest.raises(AssertionError):
        TestResponse(
            _response(headers={"x-trace": "abc"})
        ).assert_header("x-trace", "xyz")


def test_assert_header_present_and_missing() -> None:
    r = TestResponse(_response(headers={"x-foo": "y"}))
    r.assert_header_present("x-foo")
    r.assert_header_missing("x-bar")
    with pytest.raises(AssertionError):
        r.assert_header_missing("x-foo")
    with pytest.raises(AssertionError):
        r.assert_header_present("x-bar")


# ------------------------------------------------------------- body helpers


def test_assert_text_match_and_contains() -> None:
    r = TestResponse(_response(body="hello world"))
    r.assert_text("hello world")
    r.assert_text_contains("world")
    with pytest.raises(AssertionError):
        r.assert_text("nope")
    with pytest.raises(AssertionError):
        r.assert_text_contains("missing")


def test_assert_json_full_match() -> None:
    r = TestResponse(_response(json_body={"id": 1, "name": "alice"}))
    r.assert_json({"id": 1, "name": "alice"})
    with pytest.raises(AssertionError):
        r.assert_json({"id": 2})


def test_assert_json_contains() -> None:
    r = TestResponse(_response(json_body={"id": 1, "name": "alice", "extra": True}))
    r.assert_json_contains({"id": 1, "name": "alice"})
    with pytest.raises(AssertionError, match="key 'missing'"):
        r.assert_json_contains({"missing": True})
    with pytest.raises(AssertionError, match="to be 99"):
        r.assert_json_contains({"id": 99})


def test_assert_json_contains_rejects_arrays() -> None:
    r = TestResponse(_response(json_body=[1, 2, 3]))
    with pytest.raises(AssertionError, match="object body"):
        r.assert_json_contains({"id": 1})


def test_assert_json_key() -> None:
    r = TestResponse(_response(json_body={"id": 1}))
    r.assert_json_key("id")
    with pytest.raises(AssertionError):
        r.assert_json_key("missing")


def test_assert_json_count() -> None:
    r = TestResponse(_response(json_body=[1, 2, 3]))
    r.assert_json_count(3)
    with pytest.raises(AssertionError):
        r.assert_json_count(4)
    with pytest.raises(AssertionError, match="array body"):
        TestResponse(_response(json_body={"x": 1})).assert_json_count(1)


def test_chaining_returns_self() -> None:
    r = TestResponse(_response(json_body={"ok": True}))
    result = r.assert_ok().assert_header_missing("x-error").assert_json_key("ok")
    assert result is r
