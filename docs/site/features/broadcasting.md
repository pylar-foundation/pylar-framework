# Broadcasting

Pylar's broadcasting layer provides server-to-client message fan-out over WebSockets. It re-exports Starlette's `WebSocket` primitives and adds a `Broadcaster` protocol with a channel-based pub/sub model.

## The Broadcaster protocol

Every broadcaster driver implements two methods:

```python
from pylar.broadcasting import Broadcaster

class Broadcaster(Protocol):
    async def publish(self, channel: str, message: dict[str, Any]) -> None: ...
    def subscribe(self, channel: str) -> AsyncIterator[dict[str, Any]]: ...
```

`publish()` pushes a message onto a named channel. `subscribe()` returns an async iterator that yields every message subsequently published on that channel until the consumer breaks out of the loop.

## MemoryBroadcaster

The built-in in-memory driver is backed by per-subscriber `asyncio.Queue` instances. It works for single-process apps, development, and tests:

```python
from pylar.broadcasting import MemoryBroadcaster

broadcaster = MemoryBroadcaster()

# Publish from a controller or event listener
await broadcaster.publish("chat.room.1", {"user": "alice", "text": "hello"})
```

Slow consumers that fall behind have messages dropped rather than blocking the publisher. Configure limits via class attributes:

```python
broadcaster = MemoryBroadcaster()
broadcaster.max_queue_size = 500              # per-subscriber buffer (default 1000)
broadcaster.max_subscribers_per_channel = 100  # 0 = unlimited
```

Subscriber cleanup is automatic -- when the consumer breaks the async iteration loop, the queue slot is removed in a `finally` block so disconnected clients do not leak memory.

## WebSocket re-export

Import `WebSocket` and `WebSocketDisconnect` from `pylar.broadcasting` instead of reaching into Starlette directly:

```python
from pylar.broadcasting import WebSocket, WebSocketDisconnect
```

This keeps a single import point so the framework can extend these types later without breaking caller code.

## Registering WebSocket routes

Use `Router.websocket()` to register a WebSocket endpoint:

```python
from pylar.routing import Router
from pylar.broadcasting import WebSocket, WebSocketDisconnect, Broadcaster


def register_routes(router: Router, broadcaster: Broadcaster) -> None:
    async def chat_ws(ws: WebSocket) -> None:
        await ws.accept()
        channel = ws.path_params.get("room", "default")
        try:
            async for message in broadcaster.subscribe(channel):
                await ws.send_json(message)
        except WebSocketDisconnect:
            pass

    router.websocket("/ws/chat/{room}", chat_ws, name="chat")
```

## Publishing from application code

Broadcast events from controllers, event listeners, or jobs:

```python
from pylar.broadcasting import Broadcaster


class ChatController:
    def __init__(self, broadcaster: Broadcaster) -> None:
        self.broadcaster = broadcaster

    async def send_message(self, request: Request) -> Response:
        data = await request.json()
        await self.broadcaster.publish(
            f"chat.room.{data['room_id']}",
            {"user": data["user"], "text": data["text"]},
        )
        return JsonResponse({"status": "sent"})
```

## Testing

`MemoryBroadcaster` exposes introspection methods useful in tests:

```python
broadcaster = MemoryBroadcaster()

assert broadcaster.subscriber_count("chat.room.1") == 0
assert broadcaster.channels() == ()
```

For multi-process production deployments, bind a Redis-backed broadcaster instead. The `Broadcaster` protocol ensures all consumer code stays unchanged.
