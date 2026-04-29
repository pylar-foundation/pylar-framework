"""Assertion helpers for HTTP responses returned by :func:`http_client`.

The :class:`TestResponse` wraps an :class:`httpx.Response` and exposes a
fluent assertion DSL inspired by Laravel's TestResponse. Each method
returns ``self`` so checks can be chained::

    response = await client.get("/api/posts")
    (
        TestResponse(response)
        .assert_status(200)
        .assert_header("content-type", "application/json")
        .assert_json_path("$[0].title", "Hello pylar")
    )

The bare :class:`httpx.Response` is reachable via the ``raw`` attribute
when the helpers do not cover the needed shape.
"""

from __future__ import annotations

from typing import Any

import httpx


class TestResponse:
    """Fluent wrapper around :class:`httpx.Response` for HTTP assertions."""

    # The class name starts with ``Test`` because that is what users
    # actually see in their test code, but it is *not* a pytest test
    # class — tell pytest to skip collection so it does not trip the
    # discovery warning.
    __test__ = False

    def __init__(self, response: httpx.Response) -> None:
        self.raw = response

    # ----------------------------------------------------------- introspect

    @property
    def status_code(self) -> int:
        return self.raw.status_code

    @property
    def text(self) -> str:
        return self.raw.text

    def json(self) -> Any:
        return self.raw.json()

    # ----------------------------------------------------------- assertions

    def assert_status(self, expected: int) -> TestResponse:
        if self.raw.status_code != expected:
            raise AssertionError(
                f"Expected HTTP {expected}, got {self.raw.status_code}\n"
                f"Body: {self.raw.text[:500]}"
            )
        return self

    def assert_ok(self) -> TestResponse:
        return self.assert_status(200)

    def assert_created(self) -> TestResponse:
        return self.assert_status(201)

    def assert_no_content(self) -> TestResponse:
        return self.assert_status(204)

    def assert_redirect(self, location: str | None = None) -> TestResponse:
        if not (300 <= self.raw.status_code < 400):
            raise AssertionError(
                f"Expected a 3xx redirect, got {self.raw.status_code}"
            )
        if location is not None and self.raw.headers.get("location") != location:
            raise AssertionError(
                f"Expected redirect to {location!r}, "
                f"got {self.raw.headers.get('location')!r}"
            )
        return self

    def assert_unauthorized(self) -> TestResponse:
        return self.assert_status(401)

    def assert_forbidden(self) -> TestResponse:
        return self.assert_status(403)

    def assert_not_found(self) -> TestResponse:
        return self.assert_status(404)

    def assert_unprocessable(self) -> TestResponse:
        return self.assert_status(422)

    # ----------------------------------------------------------- headers

    def assert_header(self, name: str, value: str) -> TestResponse:
        actual = self.raw.headers.get(name)
        if actual != value:
            raise AssertionError(
                f"Expected header {name!r} to be {value!r}, got {actual!r}"
            )
        return self

    def assert_header_present(self, name: str) -> TestResponse:
        if name not in self.raw.headers:
            raise AssertionError(f"Expected response to carry header {name!r}")
        return self

    def assert_header_missing(self, name: str) -> TestResponse:
        if name in self.raw.headers:
            raise AssertionError(
                f"Expected response not to carry header {name!r}"
            )
        return self

    # ----------------------------------------------------------- body

    def assert_text(self, expected: str) -> TestResponse:
        if self.raw.text != expected:
            raise AssertionError(
                f"Expected body {expected!r}, got {self.raw.text!r}"
            )
        return self

    def assert_text_contains(self, fragment: str) -> TestResponse:
        if fragment not in self.raw.text:
            raise AssertionError(
                f"Expected body to contain {fragment!r}\n"
                f"Body: {self.raw.text[:500]}"
            )
        return self

    def assert_json(self, expected: Any) -> TestResponse:
        actual = self.raw.json()
        if actual != expected:
            raise AssertionError(
                f"Expected JSON body to equal {expected!r}, got {actual!r}"
            )
        return self

    def assert_json_contains(self, fragment: dict[str, Any]) -> TestResponse:
        """Assert every key/value in *fragment* is present in the JSON body.

        Useful when the response carries extra fields you do not want
        to enumerate (timestamps, ids, etc.).
        """
        actual = self.raw.json()
        if not isinstance(actual, dict):
            raise AssertionError(
                f"assert_json_contains expects an object body, got {type(actual).__name__}"
            )
        for key, expected_value in fragment.items():
            if key not in actual:
                raise AssertionError(
                    f"Expected JSON body to contain key {key!r}, got keys "
                    f"{sorted(actual.keys())}"
                )
            if actual[key] != expected_value:
                raise AssertionError(
                    f"Expected JSON body[{key!r}] to be {expected_value!r}, "
                    f"got {actual[key]!r}"
                )
        return self

    def assert_json_key(self, key: str) -> TestResponse:
        actual = self.raw.json()
        if not isinstance(actual, dict) or key not in actual:
            raise AssertionError(
                f"Expected JSON body to contain key {key!r}, got {actual!r}"
            )
        return self

    def assert_json_count(self, count: int) -> TestResponse:
        """For list responses, assert the array has exactly *count* items."""
        actual = self.raw.json()
        if not isinstance(actual, list):
            raise AssertionError(
                f"assert_json_count expects an array body, got {type(actual).__name__}"
            )
        if len(actual) != count:
            raise AssertionError(
                f"Expected JSON array to have {count} items, got {len(actual)}"
            )
        return self
