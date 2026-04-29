# views/ — backlog

## Components

Jinja2 has macros and includes; they're enough for the basic decomposition
case but feel clunky for self-contained UI fragments. A small `Component`
abstraction would let users write `<x-button>...</x-button>`-style tags
that compile to template includes plus a typed context. Open question:
worth the complexity, or do macros + partial templates already cover it?

`view.share(key, value)` and `view.with_(extras)` landed:

* :meth:`View.share` registers a process-wide layout global merged
  into every render.
* :meth:`View.with_` returns a derived View with one extra dict
  layered on top — used by per-request scopes that should not mutate
  the singleton.

## First-class layouts

Document and standardise a layout convention (`{% extends "layouts/app.html" %}`)
plus a generator under `make:view` that scaffolds a new page with the
right include / extends boilerplate. Educational rather than functional.

## Asset bundling integration

Hook into Vite / esbuild for hashed asset URLs from inside templates:
``{{ asset("app.js") }}`` reads a manifest produced by the bundler and
returns the cache-busted path.

## Streaming responses

Jinja2's async rendering can stream output chunk-by-chunk via
``render_async`` + an iterator. Expose `view.stream("template", context)`
that returns a `StreamingResponse` for very large pages.
