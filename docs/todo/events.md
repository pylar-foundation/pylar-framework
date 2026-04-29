# events/ — backlog

## ~~Queued listeners~~ ✓

`Listener.should_queue = True` landed. The bus validates that the event
is a pydantic BaseModel, serialises it as JSON, and dispatches a generic
`DispatchListenerJob` through the bound `Dispatcher`. The worker
process re-resolves the listener class, revives the event from JSON,
and calls `listener.handle(event)` in its own scope.

Wildcard MRO walk, parallel dispatch, and Subscriber classes landed:

* :meth:`EventBus.dispatch` now walks ``type(event).__mro__`` so a
  listener bound to a parent class fires for every subclass.
* :meth:`EventBus.dispatch_parallel` runs every listener via
  ``asyncio.gather`` and aggregates failures into an
  :class:`ExceptionGroup`.
* :class:`Subscriber` is the organisational base for grouping
  multiple ``bus.listen`` calls into a single class.

## ~~Test fakes~~ ✓

`FakeEventBus` landed in `pylar.testing.fakes` — recording dispatcher
with `dispatched()`, `assert_dispatched()`, `assert_not_dispatched()`.
Accessible via `EventBus.fake()`.
