# ADR-0001: Foundation principles

## Status

Accepted.

## Context

pylar is a new Python web framework that aims to combine Laravel's ergonomics
with Django's batteries-included nature, while remaining strictly typed and
async-first. Before writing code we needed to fix the principles that every
later decision will be measured against.

## Decision

### What we take from Laravel

* IoC Container with auto-wiring (typed via `Protocol` / `ABC`, no magic).
* Routing with groups and middleware groups, model binding.
* Eloquent-style models with events / scopes / accessors, but on top of
  SQLAlchemy 2.0 (typed).
* Form Requests as Request DTOs (pydantic).
* Queues / Jobs as first-class citizens.
* Policies and Gates.
* Mailables and Notifications.
* Scheduler defined in code.
* Artisan-style CLI (`pylar make:model`).
* Broadcasting.
* Domain-scoped configs (`config/database.py`, `config/queue.py`).
* Service Providers with `register` / `boot` lifecycle.

### What we take from Django

* Admin panel out of the box — auto-generated CRUD over models
  (deferred to a later phase).
* Auto-migrations (autogenerate via Alembic).
* Powerful QuerySet API (lazy, chainable, F/Q expressions) on top of
  SQLAlchemy.
* ModelForms → auto-generated DTOs from models.
* Permissions with groups.
* `gettext` for i18n.
* `manage.py`-style CLI (`pylar`).

### What we explicitly avoid

* Facades and global helpers — they break typing.
* `**kwargs` in any public API.
* Magical `__getattr__` on models without type stubs.
* A monolithic `settings.py` — replaced with a modular `config/` package.
* Static methods that hide DI.
* Dynamic properties without descriptors.
* String references to classes (`"app.models.User"`) — only real imports.

### Cross-cutting principles

1. **Protocol-first.** Every subsystem is described by `typing.Protocol` /
   `ABC`. Implementations are bound in the container. Business code never
   imports concrete classes from infrastructure layers.
2. **Async-first.** Every I/O contract is `async def`. Sync variants are kept
   only where async makes no sense (CLI bootstrap, migrations).
3. **No `**kwargs` in public APIs.** Parameters are explicit positional /
   keyword-only with types, or a dedicated pydantic DTO.
4. **Explicit over implicit.** No autodiscovery by string. Service Providers
   are listed by import in `config/app.py`.
5. **Strict mypy + ruff.** `disallow_untyped_defs`, `disallow_any_generics`,
   `strict_optional`. CI blocks regressions.
6. **One way to do one thing.** When Events exist there are no parallel
   Signals for the same use case; signals stay as a low-level lifecycle hook
   inside the ORM only.

## Consequences

* Every public function must have full type hints; the container refuses to
  resolve constructors that lack them.
* The framework cannot rely on Python's classic dynamic-attribute tricks; we
  pay for that with descriptors, generics and Protocols.
* Onboarding is harder for users coming from Laravel/Django who expect
  facades and string-based config — this is a deliberate trade-off.
