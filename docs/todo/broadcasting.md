# broadcasting/ — backlog

## ~~Persistent broadcaster drivers~~ ✓

* ~~`RedisBroadcaster`~~ ✓ — `pylar[broadcast-redis]`.
* ~~`PusherBroadcaster`~~ ✓ — `pylar[broadcast-pusher]`, HMAC-signed REST.
* `AblyBroadcaster` — deferred.

## ~~Channel authorisation~~ ✓

`BroadcastAuthorizer` shipped with the broadcasting module.

## ~~Typed message bodies~~ ✓

`BroadcastMessage` pydantic base shipped.

## Still on the wishlist

### WebSocket middleware pipeline

HTTP routes have a Pipeline of typed middleware. WebSockets currently
do not — handlers run directly. A WebSocket middleware Protocol with
`async handle(ws, next)` would let users add auth checks, logging,
and rate limiting consistently across both transports.

### Group and presence semantics

`presence` channels track the active set of subscribers and broadcast
join / leave events. Useful for chat rooms and live cursors.

### AblyBroadcaster

Third Pusher-like service. Optional dep behind
`pylar[broadcast-ably]`.
