# ADR-0008: Observability

## Status

Accepted. Opens phase 9 of the REVIEW-3 roadmap.

## Context

Pylar currently ships no observability surface. A team piloting the
framework has to glue together:

* structured logs with a request-id
* unhandled-exception capture (Sentry, Rollbar, Bugsnag)
* request/DB/queue metrics (Prometheus, StatsD, OpenTelemetry)
* distributed tracing (OpenTelemetry + Jaeger/Tempo/Datadog)
* a "what is this service even configured with?" introspection
* readiness / liveness probes for Kubernetes

Every production Django or Laravel team has this stack. For pylar the
question is *what ships in core*, *what ships behind an extras slot*,
and *what stays in user code*.

## Decision

### 1. Core ships foundations; integrations ship behind extras

Two groups of functionality:

**Core — no new dependencies:**

* `pylar/observability/` module with a single `ObservabilityServiceProvider`.
* `pylar about` — dump the resolved config: version, registered
  providers, container bindings, scheduled tasks, registered routes
  (count), queue driver, cache driver.
* `pylar doctor` — probe every bound resource (DB, cache, queue,
  storage, mail) and print a pass/fail table.
* **Structured JSON logging formatter** that correlates with the
  existing `RequestIdMiddleware` so every log line carries the
  request id.

**Optional — behind `pylar[…]` extras:**

* `pylar[otel]` — OpenTelemetry HTTP + DB + job middleware. Emits
  spans through the OTLP exporter the user configures via env vars.
* `pylar[prometheus]` — `/metrics` endpoint + HTTP / queue / DB
  collectors.
* `pylar[sentry]` — Sentry SDK provider that auto-captures unhandled
  exceptions, worker job failures, and scheduler task crashes.

Each optional integration is a **separate service provider** that the
user adds to `config/app.py`. No magic, no autodiscovery — consistent
with ADR-0001's explicit-wiring rule.

### 2. Request-id correlation is the primary observability primitive

A stable request id threaded through every log line, span, and error
report is the single cheapest thing to ship, and the one users miss
most when it isn't there. The existing `RequestIdMiddleware` already
installs `request.state.request_id`; the observability layer:

* Reads the id in the JSON log formatter and emits it as a
  top-level `request_id` field.
* Passes it as an OpenTelemetry baggage key when `pylar[otel]` is
  active.
* Attaches it to the Sentry scope when `pylar[sentry]` is active.

### 3. `pylar about` layout (Laravel-parity)

```
Application
  Name         myapp
  Version      0.4.0
  Environment  production
  Debug        false
  Base path    /srv/myapp

Database
  Driver       postgresql+asyncpg
  Name         myapp
  Host         db:5432

Cache
  Store        redis

Queue
  Driver       RedisQueue
  Queues       high (2-10), default (1-4), low (1-1)

Providers
  DatabaseServiceProvider
  CacheServiceProvider
  QueueServiceProvider
  ApiServiceProvider
  ObservabilityServiceProvider
  ...

Scheduled tasks
  0 0 * * *        daily backup
  */15 * * * *     refresh materialised views
```

Output via the existing `Output.definitions` helper so colour/alignment
matches every other command.

### 4. `pylar doctor` layout

```
Doctor — probing every bound resource

  ✓ Database             ping <3ms
  ✓ Cache                read/write roundtrip 1.1ms
  ✗ Storage (s3)         403 Forbidden — check S3_ACCESS_KEY
  ✓ Queue                size() returned without error
  ✓ Mail                 smtp.mailgun.com:587 reachable
  - Migrations           1 pending (2026_05_01_120000_add_tags)

Exit code: 1 (one failed check)
```

Failed checks exit non-zero so CI pipelines can run `pylar doctor` as
a readiness gate. Skipped checks (`-`) are informational (e.g. "no
mail transport bound").

### 5. Structured logging — JSON formatter + request-id hook

The log surface is stdlib `logging` with a new
`pylar.observability.logging.JsonFormatter`:

```json
{"timestamp": "2026-04-15T12:00:00Z", "level": "INFO",
 "logger": "pylar.queue.worker", "message": "processed 1 job",
 "request_id": "a1b2c3", "duration_ms": 47}
```

Binding it is one line in a provider:

```python
from pylar.observability.logging import install_json_logging

install_json_logging(level="INFO")
```

Consequences: logs are machine-parseable by default; humans read
them through `jq` or a Loki/Elasticsearch pipeline.

### 6. Deferred (phase 9b+)

* `pylar[otel]` — separate commit, separate extras slot.
* `pylar[prometheus]` — separate commit, separate extras slot.
* `pylar[sentry]` — separate commit, separate extras slot.

Phase 9a ships only the core surface above. Each optional
integration is a clean, self-contained follow-up.

## Phasing

* **9a — Core foundations** (this commit): module skeleton,
  `pylar about`, `pylar doctor`, JSON log formatter, provider wiring.
  No new dependencies.
* **9b — OpenTelemetry**: middleware + extras + docs.
* **9c — Prometheus**: `/metrics` + collectors + extras + docs.
* **9d — Sentry**: provider + extras + docs.

## Consequences

* The framework grows one module and a provider. Zero runtime deps in
  the base install — users who never run `pylar about` or bind the
  JSON formatter pay nothing.
* The Laravel / Django parity bar on "infra readiness" rises: new
  installations get a working diagnostic story out of the box.
* The optional-extras pattern (already established by queue, cache,
  session, storage, mail) is reused — consistent with ADR-0003 and
  ADR-0005.
* `pylar doctor` becomes the framework's equivalent of
  `./manage.py check` / `php artisan env`. CI pipelines are
  encouraged to run it as a pre-boot gate.

## References

* REVIEW-3 section 6 — phase 9 scope.
* ADR-0001 (explicit wiring, no magic).
* ADR-0005 (entry points — future `pylar-otel`, `pylar-prometheus`
  packages could live here).
