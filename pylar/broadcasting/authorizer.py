"""Channel authorization for private WebSocket subscriptions.

The :class:`BroadcastAuthorizer` is a registry of callbacks that
gate access to private channels. Register authorization rules in a
service provider, then call :meth:`authorize` from your WebSocket
handler before yielding the subscription iterator::

    authorizer = BroadcastAuthorizer()
    authorizer.channel(
        "private-orders.{order_id}",
        lambda user, order_id: user.id == int(order_id),
    )

    # In the WebSocket handler:
    if not await authorizer.authorize(user, channel_name):
        await ws.close(code=4003)
        return
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

from pylar.auth.contracts import Authenticatable

#: A channel callback receives the authenticated user and any captured
#: path segments from the channel pattern. It must return True to allow
#: the subscription.
ChannelCallback = Callable[..., bool | Awaitable[bool]]


class BroadcastAuthorizer:
    """Gate access to private broadcast channels."""

    def __init__(self) -> None:
        self._channels: list[tuple[re.Pattern[str], ChannelCallback]] = []

    def channel(self, pattern: str, callback: ChannelCallback) -> None:
        """Register an authorization rule for channels matching *pattern*.

        *pattern* uses ``{name}`` placeholders that capture path segments
        (like route patterns)::

            authorizer.channel("private-user.{user_id}", check_user)
        """
        regex_str = re.sub(
            r"\{(\w+)\}",
            r"(?P<\\1>[^.]+)",
            re.escape(pattern).replace(r"\{", "{").replace(r"\}", "}"),
        )
        # Simpler: convert {name} to named groups
        regex_str = re.sub(r"\\\{(\w+)\\\}", r"(?P<\1>[^.]+)", re.escape(pattern))
        self._channels.append((re.compile(f"^{regex_str}$"), callback))

    async def authorize(
        self,
        user: Authenticatable | None,
        channel: str,
    ) -> bool:
        """Return ``True`` if *user* may subscribe to *channel*."""
        if user is None:
            return False

        for regex, callback in self._channels:
            match = regex.match(channel)
            if match is not None:
                result = callback(user, **match.groupdict())
                if isinstance(result, bool):
                    return result
                return bool(await result)

        # No rule matched → deny by default.
        return False
