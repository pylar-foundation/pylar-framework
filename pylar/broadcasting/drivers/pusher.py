"""Pusher Channels broadcaster — HTTP-REST publish to Pusher's cloud service.

Unlike :class:`MemoryBroadcaster` and :class:`RedisBroadcaster`,
Pusher is a *publish-only* driver from the server's perspective:
clients subscribe directly to Pusher's WebSocket edge network via
the ``pusher-js`` / ``Echo`` JS SDKs. Server-side code only pushes
events.

Install via ``pylar[broadcast-pusher]`` (pulls in ``httpx`` — we
issue the REST call directly so the official sync ``pusher`` SDK
isn't a hard dep and the driver stays async-native).

Usage::

    from pylar.broadcasting.drivers.pusher import PusherBroadcaster

    broadcaster = PusherBroadcaster(
        app_id=env.str("PUSHER_APP_ID"),
        key=env.str("PUSHER_KEY"),
        secret=env.str("PUSHER_SECRET"),
        cluster=env.str("PUSHER_CLUSTER"),  # e.g. "eu"
    )

    await broadcaster.publish("orders", {"event": "created", "order_id": 42})

The driver implements :class:`pylar.broadcasting.Broadcaster`;
:meth:`subscribe` raises :class:`PusherSubscribeNotSupportedError` because
the fan-out happens on the client edge, not through this process.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlencode

try:
    import httpx
except ImportError:  # pragma: no cover
    raise ImportError(
        "PusherBroadcaster requires httpx. "
        "Install with: pip install 'pylar[broadcast-pusher]'"
    ) from None

from pylar.broadcasting.exceptions import BroadcastingError


class PusherSubscribeNotSupportedError(BroadcastingError):
    """Raised by :meth:`PusherBroadcaster.subscribe` — server-side subscribe
    is not a concept in Pusher Channels; clients subscribe through Pusher's
    WebSocket edge."""


PusherSubscribeNotSupported = PusherSubscribeNotSupportedError


class PusherBroadcaster:
    """Publish events to Pusher Channels via the HTTP-REST API.

    Signing follows the Pusher spec: the body is MD5-hashed, the
    request metadata plus the body hash is HMAC-SHA256 signed with
    the application secret, and the signature is appended to the URL
    as ``auth_signature``.

    *event_name* on :meth:`publish` defaults to
    ``"pylar.broadcast"``; callers that want a different event name
    pass the ``event`` key in the message dict and the driver picks
    it up automatically — same convention Laravel Echo uses.
    """

    def __init__(
        self,
        *,
        app_id: str,
        key: str,
        secret: str,
        cluster: str = "eu",
        host: str | None = None,
        timeout: float = 5.0,
    ) -> None:
        self._app_id = app_id
        self._key = key
        self._secret = secret.encode()
        self._host = host or f"api-{cluster}.pusher.com"
        self._timeout = timeout

    async def publish(self, channel: str, message: dict[str, Any]) -> None:
        event_name = str(message.pop("event", "pylar.broadcast"))
        body = json.dumps(
            {
                "name": event_name,
                "channel": channel,
                "data": json.dumps(message),
            },
            separators=(",", ":"),
        )

        path = f"/apps/{self._app_id}/events"
        body_md5 = hashlib.md5(body.encode()).hexdigest()
        auth_params = {
            "auth_key": self._key,
            "auth_timestamp": str(int(time.time())),
            "auth_version": "1.0",
            "body_md5": body_md5,
        }
        signed_params = sorted(auth_params.items())
        canonical = "\n".join([
            "POST",
            path,
            urlencode(signed_params),
        ])
        signature = hmac.new(
            self._secret, canonical.encode(), hashlib.sha256,
        ).hexdigest()
        params = dict(signed_params) | {"auth_signature": signature}
        url = f"https://{self._host}{path}?{urlencode(params)}"

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                url,
                content=body,
                headers={"Content-Type": "application/json"},
            )
        if response.status_code >= 400:
            raise BroadcastingError(
                f"Pusher rejected publish: {response.status_code} {response.text}"
            )

    def subscribe(self, channel: str) -> AsyncIterator[dict[str, Any]]:
        """Pusher's server does not expose server-side subscribe — clients
        connect through Pusher's own WebSocket edge."""
        raise PusherSubscribeNotSupported(
            "PusherBroadcaster is publish-only — clients subscribe through "
            "Pusher's WebSocket edge (pusher-js / Laravel Echo)."
        )
