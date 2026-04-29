# ADR-0005: Package autodiscovery via entry points

## Status

Accepted. Supersedes the "no autodiscovery" clause in ADR-0001 for
third-party packages (user project providers remain explicit).

## Context

ADR-0001 states "service providers listed by import, not scanned."
This works well for first-party providers within a project, but
becomes a pain point when the ecosystem grows: installing a pylar
plugin package (e.g. `pip install pylar-admin`) should not require
the user to manually edit `config/app.py`.

Laravel solved this with composer.json `extra.laravel.providers`.
Python has a native equivalent: **entry points** via
`importlib.metadata`.

## Decision

| # | Concern | Choice |
|---|---|---|
| 1 | Discovery mechanism | Python entry points under `pylar.providers` group |
| 2 | Default behavior | `AppConfig.autodiscover=True` — packages auto-loaded |
| 3 | Opt-out | `autodiscover=False` disables all discovery |
| 4 | Ordering | Explicit providers first, discovered appended after |
| 5 | Deduplication | If a discovered class is already in explicit list, skip it |
| 6 | Validation | Loaded classes must be `ServiceProvider` subclasses |
| 7 | Error handling | Broken plugins logged and skipped, app still starts |
| 8 | Inspection | `pylar package:list` shows installed plugins without loading |

### How third-party packages register

```toml
# In the package's pyproject.toml:
[project.entry-points."pylar.providers"]
admin = "pylar_admin.provider:AdminServiceProvider"
```

After `pip install pylar-admin`, the provider is discovered
automatically on next app boot.

### Bootstrap flow

1. Explicit providers from `AppConfig.providers` are instantiated
2. If `autodiscover=True`, `discover_providers()` scans entry points
3. Discovered classes not already in the explicit set are appended
4. All providers go through register → boot lifecycle

## Consequences

* Third-party packages "just work" after `pip install` — no manual
  config editing needed.
* User projects retain full control: explicit providers in
  `config/app.py` always run first, and `autodiscover=False`
  disables the mechanism entirely.
* The `pylar package:list` command gives visibility into what's
  installed without loading any plugin code.
* This is the mechanism needed to extract `pylar/admin/` into a
  separate `pylar-admin` package later.
