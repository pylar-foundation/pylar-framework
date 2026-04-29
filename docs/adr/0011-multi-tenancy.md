# ADR-0011: Multi-tenancy

## Status

Accepted. Opens phase 13b of the REVIEW-3 roadmap.

## Context

SaaS applications isolate customer data in one of three common
patterns:

1. **Shared database, column-per-tenant** — every table has a
   `tenant_id` foreign key; queries auto-scope.
2. **Schema-per-tenant** — one Postgres schema per tenant, shared
   database server; the `search_path` switches per request.
3. **Database-per-tenant** — completely isolated databases;
   connections swap per request.

Django reaches for `django-tenants` (schema or DB). Laravel uses
`stancl/tenancy` or `tenancyforlaravel.com`. Both require framework
hooks at four layers: request identification (subdomain, path,
header), connection routing, migration tooling, and a tenant model.

Pylar has none of this. The ADR defines the minimal surface that lets
an application adopt any of the three patterns without the framework
getting in the way.

## Decision

### 1. Tenant identification — middleware-driven

A new :class:`TenantMiddleware` resolves the active tenant from the
incoming request and stores it in a :class:`ContextVar`. The
resolution strategy is pluggable via a :class:`TenantResolver`
Protocol:

```python
class TenantResolver(Protocol):
    async def resolve(self, request: Request) -> Tenant | None: ...
```

Three resolvers ship in core:

* `SubdomainTenantResolver` — reads `tenant.example.com` and looks
  the slug up. Matches the `tenancy` package's default.
* `HeaderTenantResolver` — reads `X-Tenant-ID`.
* `PathPrefixTenantResolver` — reads `/t/{tenant_slug}/...` from
  the URL.

Apps bind whichever resolver they need via the container; the
middleware calls it, sets the contextvar, and every downstream layer
(queries, caching, storage paths, mail from addresses) reads the
active tenant without explicit threading.

### 2. Tenant model

A minimal :class:`Tenant` base model:

```python
class Tenant(Model):
    class Meta:
        db_table = "tenants"

    slug = CharField(unique=True)
    name = CharField()
    domain = CharField(unique=True, null=True)
    database_url = CharField(null=True)     # for DB-per-tenant
    schema_name = CharField(null=True)      # for schema-per-tenant
    is_active = BooleanField(default=True)
```

Apps subclass to add billing, plan tier, etc.

### 3. Scoping strategy — three tiers

#### Tier A: Column isolation (simplest)

A `TenantScopedMixin` auto-injects `WHERE tenant_id = current_tenant().id`
on every QuerySet call. The scoping is transparent — user code writes
`Post.query.all()` and gets back only the active tenant's rows.

The mixin overrides `QuerySet._build_select` to prepend the clause
so it cannot be accidentally omitted. `Model.save()` stamps
`tenant_id` on create if it is not already set.

#### Tier B: Schema isolation (Postgres)

`SchemaTenantManager` extends :class:`ConnectionManager`:

* `set_search_path(schema_name)` — issues `SET search_path TO <schema>, public`
  at the start of a session.
* The middleware wires this after resolving the tenant; every query
  in the request scope hits the tenant's schema.

Migrations: `pylar migrate --tenant=<slug>` runs Alembic against
that schema. `pylar migrate:all-tenants` loops over every active
tenant.

#### Tier C: Database isolation

`DatabasePerTenantManager` swaps the `ConnectionManager` engine per
request based on `Tenant.database_url`. The middleware looks up the
URL, opens (or reuses from a pool) an engine for that database, and
installs it as the ambient session's bind. Cross-tenant queries are
impossible by construction.

### 4. Caching + storage + queue scoping

When a tenant is active:

* **Cache**: keys auto-prefixed with `tenant:<slug>:` via a
  `TenantCacheStore` wrapper.
* **Storage**: file paths prefixed with `tenants/<slug>/`.
* **Queue**: `record.queue` can carry a per-tenant name
  (`high:acme`) if the app wants per-tenant priority lanes; this is
  opt-in, not automatic.

### 5. Console tooling

* `pylar tenants:list` — table of active tenants.
* `pylar tenants:migrate --tenant=<slug>` — run migrations against
  one tenant.
* `pylar tenants:migrate-all` — loop over every active tenant.
* `pylar tenants:seed --tenant=<slug>` — run seeders scoped to a
  tenant.

### 6. Phasing

This ADR is **design-only for tiers B and C**. The code shipped in
13b covers:

* The `Tenant` base model.
* `TenantMiddleware` + `current_tenant()` contextvar + three
  resolvers.
* `TenantScopedMixin` (tier A column isolation).
* `TenantServiceProvider`.

Schema isolation (tier B) and database isolation (tier C) ship in a
follow-up once a real project validates the design on Postgres. The
ADR captures the full plan so the tier A code is shaped to not block
B/C.

## Consequences

* **New module**: `pylar/tenancy/` — provider, middleware, model,
  resolvers, mixin.
* **No new deps** — everything builds on existing SA + contextvars.
* **Migration**: apps that adopt tenancy add the `tenants` table and
  a `tenant_id` FK on every scoped model. The mixin enforces the FK
  at the query level; the migration is the app's responsibility.
* **Backwards compat**: apps that don't import from `pylar.tenancy`
  are unaffected. The contextvar defaults to `None`; the mixin is
  opt-in.

## References

* REVIEW-3 section 6.3 — ecosystem hardening.
* ADR-0001 (explicit wiring).
* django-tenants: https://django-tenants.readthedocs.io
* stancl/tenancy: https://tenancyforlaravel.com
