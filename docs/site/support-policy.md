# Support Policy

This page is the short-form, adopter-facing version of [ADR-0010:
LTS cadence and SemVer contract](architecture/adrs.md). Read the ADR
for the full reasoning; this page answers the three questions most
adopters ask before committing.

## Versioning

Pylar follows [Semantic Versioning 2.0](https://semver.org).

| Bump | Meaning | Example |
|---|---|---|
| **major** (1.x → 2.x) | Public API may break. Migration guide published. | 1.8 → 2.0 |
| **minor** (1.a → 1.b) | Additive only: new modules, new methods, new drivers. Private APIs may move. | 1.4 → 1.5 |
| **patch** (1.a.b → 1.a.c) | Bug fixes + security patches only. | 1.4.2 → 1.4.3 |

### Current pre-1.0 caveat

**The currently published line is `0.1.0`.** This is the initial
public release. Until `1.0.0` ships, expect:

- minor bumps (`0.x → 0.y`) may include breaking changes — review
  release notes before every upgrade;
- pin exact versions in your lockfile (`pylar-framework==0.1.0`);
- compatibility guarantees apply within a single `0.x` line only.

Once `1.0.0` ships, the normal 1.x SemVer contract below applies.

## What counts as a "public API"

The public API is everything reachable from a module's top-level
import:

```python
from pylar.queue import Job, QueueConfig        # public ✓
from pylar.auth import TokenMiddleware          # public ✓
from pylar.queue.worker import _EffectivePolicy # NOT public (leading _)
```

Specifically:

* Every symbol in `__all__` of a top-level module.
* Every parameter name, default, and type hint on a public callable.
* Documented behaviour in module ADRs or docstrings.

**Not** public:

* Names starting with `_`.
* Submodules not re-exported at `pylar.<mod>.__init__`.
* Internal class attributes used for plumbing.
* File formats that aren't themselves published APIs (raw Alembic
  migration files, wire-format bytes).

## Release cadence (1.x after GA)

| Channel | Frequency | Support window |
|---|---|---|
| Minor (non-LTS) | every ~3 months | 12 months |
| Minor (LTS) | every 4th minor | 24 months |
| Patch | on demand | follows the minor |
| Major | every ~12 months | see below |

Every fourth minor is marked **LTS** (1.0, 1.4, 1.8, …). Between LTS
lines, non-LTS minors still receive 12 months of support. Teams that
prefer a slow cadence can hop LTS → LTS once a year and always stay
inside support.

Majors (2.x, 3.x) don't ship more often than every 12 months and
always come with a published migration guide.

## Deprecation policy

A public API marked `@deprecated` keeps working for **one full minor
cycle** (~3 months) before it's removed. You'll know about it three
ways:

1. The docstring gets a `.. deprecated:: 1.4 — use X instead` note.
2. The changelog entry lists the deprecation under "Deprecated".
3. Importing the deprecated symbol raises `DeprecationWarning` at
   import time, so your CI catches the usage.

## Security fixes

| | |
|---|---|
| **Reporting** | `pylar-foundation@vsibiri.info` or GitHub Security Advisories on the affected repository. |
| **Response** | Initial acknowledgement within 3 business days; fix timing depends on severity. |
| **Backport** | Every supported line listed in the [Release cadence](#release-cadence-1x-after-ga) section gets the fix. |
| **Disclosure** | Repository advisory or security notice + changelog entry, with upgrade instructions. |

## Plugin ecosystem

First-party plugin packages (`pylar-admin`, `pylar-stripe`,
`pylar-passport`, …) follow the same SemVer rules but track their
own versions. Each plugin's README publishes a compatibility matrix:

```
pylar-admin 0.1.0 supports pylar-framework 0.1.x
pylar-admin 1.x  supports pylar-framework 1.0 – 1.8
```

The [ADR-0005 entry-point mechanism](architecture/adrs.md) means a
plugin can be picked up by any compatible core version without code
changes on the user's side.

## What to do if...

**...you're pinning for production:**

* Pin `pylar-framework==X.Y.Z` (exact) in your lockfile.
* Track the changelog. Deprecation warnings in CI are the signal
  to upgrade.
* Stay on LTS lines for slower churn once 1.0 ships.

**...you're prototyping on a 0.x line:**

* Pin the exact patch (`pylar-framework==0.1.0`) and read the
  changelog before any minor bump — `0.x` allows breaking changes
  between minors.

**...you hit a CVE:**

* Upgrade to the latest patch release of your minor.
* If your minor is past end-of-life, upgrade to the latest LTS or
  the latest minor — the ADR-0010 policy guarantees a patched path
  exists.
