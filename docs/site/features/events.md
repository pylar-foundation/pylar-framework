# Events

Pylar's event system provides typed, async event dispatching with support for sequential and parallel execution, queued listeners, and subscribers.

## Defining Events

Events are simple frozen dataclasses that extend `Event`:

```python
from dataclasses import dataclass
from pylar.events import Event

@dataclass(frozen=True)
class PostPublished(Event):
    post_id: int
    author_id: int
```

## Defining Listeners

A listener is a typed class that handles a specific event:

```python
from pylar.events import Listener

class NotifySubscribers(Listener[PostPublished]):
    def __init__(self, mailer: Mailer) -> None:
        self.mailer = mailer

    async def handle(self, event: PostPublished) -> None:
        subscribers = await Subscription.objects.filter(author_id=event.author_id).all()
        for sub in subscribers:
            await self.mailer.send(NewPostMail(sub.email, event.post_id))
```

Listener constructors are auto-wired by the container — declare dependencies as typed parameters.

## Registering Listeners

Register listeners in your `EventServiceProvider`:

```python
from pylar.events import EventBus

class EventServiceProvider(ServiceProvider):
    async def boot(self) -> None:
        bus = self.app.make(EventBus)
        bus.listen(PostPublished, NotifySubscribers)
        bus.listen(PostPublished, UpdateSearchIndex)
```

Multiple listeners can be registered for the same event. They execute in registration order.

## Dispatching Events

```python
from pylar.events import EventBus

bus: EventBus  # auto-wired

# Sequential dispatch (listeners run one at a time):
await bus.dispatch(PostPublished(post_id=1, author_id=42))

# Parallel dispatch (listeners run concurrently via asyncio.gather):
await bus.dispatch_parallel(PostPublished(post_id=1, author_id=42))
```

`dispatch_parallel` collects errors into an `ExceptionGroup` if any listener fails.

## Queued Listeners

For expensive work, mark a listener as queued — it is dispatched via the queue module instead of running inline:

```python
class RebuildSearchIndex(Listener[PostPublished]):
    should_queue = True

    async def handle(self, event: PostPublished) -> None:
        await search.reindex_post(event.post_id)
```

!!! note
    Queued listeners require the event to be a Pydantic `BaseModel` (for serialization) and a `Dispatcher` in the container.

## Subscribers

Group multiple listener registrations into a single class:

```python
from pylar.events import Subscriber, EventBus

class PostSubscriber(Subscriber):
    def subscribe(self, bus: EventBus) -> None:
        bus.listen(PostPublished, NotifySubscribers)
        bus.listen(PostPublished, UpdateSearchIndex)
        bus.listen(PostDeleted, RemoveFromIndex)
```

## Testing

```python
from pylar.events import EventBus

fake = EventBus.fake()
await fake.dispatch(PostPublished(post_id=1, author_id=42))

# Listeners are NOT executed — the fake records dispatched events for assertions
```
