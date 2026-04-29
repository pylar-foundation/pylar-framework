"""Chainable async pipeline — avoid writing ``await`` on every step.

Sequences of async calls where each feeds the next read cleanly with
:func:`pipe`::

    # Instead of:
    post = await Post.query.get(1)
    post.title = "Updated"
    saved = await Post.query.save(post)

    # Write:
    saved = await (
        pipe(Post.query.get(1))
        .then(lambda p: setattr(p, "title", "Updated") or p)
        .then(Post.query.save)
    )

The initial ``seed`` is a value, coroutine, or any awaitable. Each
``.then(fn)`` applies ``fn(value)`` and awaits the result if it is
itself a coroutine. ``.tap(fn)`` runs ``fn`` for side effects and
passes the original value through — handy for logging mid-chain.

For a flat sequence of independent coroutines use :func:`sequence`::

    last_result = await sequence(
        bus.dispatch(UserCreated(id=1)),
        bus.dispatch(UserWelcomed(id=1)),
        mailer.send(welcome_mail),
    )
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Generator
from typing import Any, TypeVar

T = TypeVar("T")
U = TypeVar("U")


class AsyncPipe[T]:
    """A chainable wrapper around an awaitable value.

    Instances are created via :func:`pipe`. Each chained method
    returns a new :class:`AsyncPipe` — nothing executes until the
    pipeline is awaited.
    """

    __slots__ = ("_seed",)

    def __init__(self, seed: Awaitable[T] | T) -> None:
        self._seed = seed

    def then[U](self, fn: Callable[[T], Awaitable[U] | U]) -> AsyncPipe[U]:
        """Chain ``fn`` onto the pipeline.

        ``fn`` receives the resolved value from the previous step. If
        ``fn`` returns a coroutine it is awaited; otherwise the return
        value flows through as-is.
        """

        async def _step() -> U:
            value = await _resolve(self._seed)
            result = fn(value)
            return await _resolve(result)

        return AsyncPipe(_step())

    def tap(self, fn: Callable[[T], Awaitable[Any] | Any]) -> AsyncPipe[T]:
        """Run ``fn(value)`` for side effects, forward the original value.

        Useful for mid-chain logging without breaking the data flow::

            pipe(load()).tap(print).then(process)
        """

        async def _step() -> T:
            value = await _resolve(self._seed)
            result = fn(value)
            await _resolve(result)
            return value

        return AsyncPipe(_step())

    def __await__(self) -> Generator[Any, None, T]:
        async def _run() -> T:
            return await _resolve(self._seed)

        return _run().__await__()


async def _resolve[T](value: Awaitable[T] | T) -> T:
    if inspect.isawaitable(value):
        return await value
    return value


def pipe[T](seed: Awaitable[T] | T) -> AsyncPipe[T]:
    """Start an async pipeline from *seed* (value, coroutine, or awaitable)."""
    return AsyncPipe(seed)


async def sequence(*awaitables: Awaitable[Any] | Any) -> Any:
    """Await each argument in order, return the final value.

    Non-awaitable arguments pass through unchanged::

        last = await sequence(
            cache.forget("key"),
            Post.query.count(),
            log("done"),
        )
    """
    result: Any = None
    for item in awaitables:
        result = await _resolve(item)
    return result
