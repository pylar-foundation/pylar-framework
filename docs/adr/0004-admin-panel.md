# ADR-0004: Admin Panel Architecture

## Status

Accepted.

## Context

ADR-0003 deferred the admin panel, noting a preference for HTMX
server-rendered UI.  After reconsideration, the decision was revised
to build a **Vue.js SPA** (similar to Laravel Nova) for richer
interactivity, while keeping the panel as an **optional, disableable
module** that no other part of pylar depends on.

## Decision

| # | Concern | Choice | Notes |
|---|---|---|---|
| 1 | Frontend | **Vue.js 3 SPA** (Composition API, Pinia, Vue Router) | Richer interactivity than HTMX. No server-rendered HTML for admin views. |
| 2 | API | **JSON REST API** under `{prefix}/api/` | Clean separation: backend is a data provider, frontend handles all UI. |
| 3 | Build tool | **Vite** | Fast dev server, tree-shaking, TypeScript out of the box. |
| 4 | Bundling | Pre-built `dist/` in the Python package | No Node.js required at runtime. Developers can rebuild from source. |
| 5 | Optional module | `AdminServiceProvider` in providers list | Remove the provider to disable. `AdminConfig.enabled = False` also works. |
| 6 | Auth | Reuses existing `AuthMiddleware` + `RequireAuthMiddleware` | No separate admin auth system. Gate abilities for fine-grained control. |
| 7 | Static serving | Route-based (`GET {prefix}/assets/{path}`) | Self-contained — no changes to HttpKernel or Starlette mounts. |
| 8 | Model introspection | SQLAlchemy `inspect()` at registration time | Auto-generates list_display, form_fields, search_fields from column metadata. |
| 9 | Styling | Custom CSS variables, dark/light mode | No Tailwind or external CSS framework. Minimal footprint (~150 lines). |

## Consequences

* The admin panel has zero coupling to the rest of pylar — removing
  `AdminServiceProvider` from the providers tuple removes all admin
  routes, controllers, and bindings.
* The Vue.js source lives inside the package at `pylar/admin/spa/`.
  The built assets at `pylar/admin/spa/dist/` are served by a regular
  pylar route handler.
* A Node.js toolchain is only needed to modify or rebuild the SPA.
  Users who just consume the admin use the pre-built dist.
* The JSON API design means the admin can be consumed by custom
  frontends or automated tools.
