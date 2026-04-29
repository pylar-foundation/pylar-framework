# routing/ — backlog

The big v1 ergonomics gaps (fluent builder, model binding, reverse
routing, resource controllers) all landed in the routing v1.5 batch.
What is still on the wishlist:

## ~~Per-route caching helpers~~ ✓

`router.get(...).cache(seconds=60)` landed. The `CacheResponseMiddleware`
caches full GET responses via the Cache facade, serves from cache on hit,
and invalidates on mutating methods. Subclass to customise key generation.

## ~~Rate limiting middleware~~ ✓

`pylar.routing.ThrottleMiddleware` (and its `TooManyRequests` 429
exception) landed — backed by ``Cache.increment``, keyed by client IP
+ path by default. Subclass and override ``identity_for`` to key by
authenticated user id, API key, etc.

`pylar.auth.LoginThrottleMiddleware` added as a tighter variant
(5 req/60s) specifically for auth endpoints.

## Route caching

`pylar route:cache` precompiles every registered route into a Python
file that the kernel imports at boot, skipping the per-request scan.
Laravel does this for big projects; only worth chasing once a real
project complains about boot time.
