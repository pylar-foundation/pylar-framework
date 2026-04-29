"""Tests for :class:`PusherBroadcaster` — HMAC signing + REST publish."""

from __future__ import annotations

import hashlib
import hmac
import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from pytest import MonkeyPatch

from pylar.broadcasting.drivers.pusher import (
    PusherBroadcaster,
    PusherSubscribeNotSupported,
)
from pylar.broadcasting.exceptions import BroadcastingError


def _stub_transport(captured: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"ok": True})

    return httpx.MockTransport(handler)


async def test_publish_builds_signed_pusher_request(
    monkeypatch: MonkeyPatch,
) -> None:
    captured: list[httpx.Request] = []

    # Patch the client factory so the test owns the transport without
    # touching real network.
    original_client = httpx.AsyncClient

    def patched_client(
        *args: object,
        **kwargs: object,
    ) -> httpx.AsyncClient:
        return original_client(*args, transport=_stub_transport(captured), **kwargs)

    monkeypatch.setattr("pylar.broadcasting.drivers.pusher.httpx.AsyncClient", patched_client)

    bc = PusherBroadcaster(
        app_id="A1", key="k_pub", secret="s_sec", cluster="eu",
    )
    await bc.publish("orders", {"event": "created", "order_id": 42})

    assert len(captured) == 1
    req = captured[0]
    assert req.method == "POST"
    assert req.url.host == "api-eu.pusher.com"

    # Body carries the event metadata; data is re-encoded JSON minus
    # the `event` key, which is promoted to the top-level `name` field.
    body = json.loads(req.content.decode())
    assert body["name"] == "created"
    assert body["channel"] == "orders"
    assert json.loads(body["data"]) == {"order_id": 42}

    # Signature is a valid SHA256 HMAC of the canonical request.
    query = {k: v[0] for k, v in parse_qs(urlparse(str(req.url)).query).items()}
    assert query["auth_key"] == "k_pub"
    assert query["auth_version"] == "1.0"
    assert query["body_md5"] == hashlib.md5(req.content).hexdigest()

    signed = sorted(
        (k, v) for k, v in query.items() if k != "auth_signature"
    )
    from urllib.parse import urlencode as _enc

    canonical = "\n".join(["POST", "/apps/A1/events", _enc(signed)])
    expected = hmac.new(
        b"s_sec", canonical.encode(), hashlib.sha256,
    ).hexdigest()
    assert query["auth_signature"] == expected


async def test_publish_defaults_event_name_when_omitted(
    monkeypatch: MonkeyPatch,
) -> None:
    captured: list[httpx.Request] = []
    original_client = httpx.AsyncClient

    def patched_client(
        *args: object,
        **kwargs: object,
    ) -> httpx.AsyncClient:
        return original_client(*args, transport=_stub_transport(captured), **kwargs)

    monkeypatch.setattr("pylar.broadcasting.drivers.pusher.httpx.AsyncClient", patched_client)

    bc = PusherBroadcaster(app_id="A", key="K", secret="S")
    await bc.publish("x", {"payload": 1})

    body = json.loads(captured[0].content.decode())
    assert body["name"] == "pylar.broadcast"


async def test_publish_raises_on_non_2xx_response(
    monkeypatch: MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="forbidden")

    original_client = httpx.AsyncClient

    def patched_client(
        *args: object,
        **kwargs: object,
    ) -> httpx.AsyncClient:
        return original_client(
            *args, transport=httpx.MockTransport(handler), **kwargs,
        )

    monkeypatch.setattr("pylar.broadcasting.drivers.pusher.httpx.AsyncClient", patched_client)

    bc = PusherBroadcaster(app_id="A", key="K", secret="S")
    with pytest.raises(BroadcastingError, match="403"):
        await bc.publish("x", {})


async def test_subscribe_is_unsupported_on_pusher() -> None:
    bc = PusherBroadcaster(app_id="A", key="K", secret="S")
    with pytest.raises(PusherSubscribeNotSupported):
        bc.subscribe("orders")
