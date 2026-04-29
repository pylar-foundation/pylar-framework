# ADR-0010: LTS cadence and SemVer contract

## Status

Accepted. Opens phase 13 of the REVIEW-3 roadmap.

## Context

Real teams evaluating pylar want to know, before committing, three
operational questions the framework has not yet answered in writing:

1. **What counts as a breaking change?** If a method's signature
   moves behind a kwarg-only barrier, is that breaking? If an
   internal helper's name changes and someone imported it from a
   private path, is that breaking?
2. **How long is a given release line supported?** Production
   systems pin and roll forward at their own pace; a framework that
   ships minor versions every six weeks without a clear support
   promise is a pin that will either drift or never roll.
3. **When do security fixes backport to older lines?** A CVE in
   pylar 0.6.x needs to reach teams still on 0.5.x without forcing
   them onto a whole new minor.

Django and Laravel both publish these commitments. Pylar hasn't, and
the review-3 gap analysis called it out as an adoption blocker. This
ADR fills it.

## Decision

### 1. SemVer with an explicit pre-1.0 disclaimer

Pylar follows [Semantic Versioning 2.0](https://semver.org), with one
explicit caveat documented in the README and the changelog: the
current `1.0.0rc1` line is a release candidate and must be pinned
exactly until `1.0.0` GA ships. RC builds may still tighten APIs
before the stable 1.0 contract takes effect, and each such change is
called out in the changelog with a migration note.

Once 1.0 lands, SemVer applies strictly:

* **Major (1.x → 2.x)** — may break the public API, requires a
  published migration guide, ships no sooner than 12 months after
  the previous major.
* **Minor (1.a → 1.b)** — additive only: new modules, new public
  methods, new extras slots, new drivers. May change private APIs
  (anything not in the public surface defined below).
* **Patch (1.a.b → 1.a.c)** — bug fixes, security patches, doc
  updates. Never adds public API.

### 2. Definition of the public API

The public API is every name reachable by importing from the
top-level of a shipped module:

```python
from pylar.queue import Job, QueueConfig        # public
from pylar.auth import TokenMiddleware          # public
from pylar.database import Model, transaction   # public
```

Specifically, the public API covers:

* Every symbol listed in a module's `__all__`.
* Every symbol re-exported at `pylar.<module>.__init__`.
* The signature (names, types, defaults) of every public callable,
  both module-level and method-level.
* The observable behaviour documented in the module's ADR or
  docstring — if the docstring promises "no retry beyond
  `max_attempts`", the promise is part of the contract.

The public API does **not** cover:

* Anything reachable only by deep-importing a submodule not
  mentioned in the parent `__init__.py`.
* Any name starting with `_`.
* Internal class attributes used for container plumbing (e.g.
  `_stopping`, `_queues`).
* Wire-format details that are not themselves published APIs
  (e.g. the exact structure of an Alembic migration file).

### 3. Release cadence

* **Minor releases**: one every 3 months during the 1.x series. A
  minor line's support window is **12 months** — e.g. 1.4 ships in
  April, drops out of support April next year.
* **Major releases**: not more often than every 12 months. We will
  actively avoid a 2.x before the ecosystem has a settled 1.x.
* **Patch releases**: on demand. A patch can ship a week after the
  minor if a regression warrants it.

During the current RC period, builds ship when ready. There is no LTS
on RC builds — adopters pin the exact version and upgrade on their
own cadence until `1.0.0` is final.

### 4. Deprecation policy

A public API marked `@deprecated` keeps working for **one full minor
cycle** (~3 months) before removal. Deprecations are announced:

* In the symbol's docstring (`.. deprecated:: 1.4 — use X instead`).
* In the changelog entry for the minor that introduced the warning.
* At import time via `warnings.warn(DeprecationWarning)` so
  downstream CI catches usage.

Removal in the next minor (1.5 in this example) ships alongside the
deprecation note repeated under "Removed in this release" in the
changelog.

### 5. Security policy

A CVE-level issue in any supported line is triaged immediately after
reproduction. Backports follow the repository support matrix.
Security advisories are published via the repository's advisory
process plus a changelog entry linking to the fix commit and upgrade
instructions.

Reports go to `security@pylarframework.dev` (placeholder — the real
address goes live when the framework moves to its permanent domain).
PGP-encrypted reports are accepted; unencrypted reports are fine too.

### 6. LTS lines (post-1.0)

Every fourth minor is marked LTS and supported for **24 months** —
e.g. 1.0 LTS, 1.4 LTS, 1.8 LTS. Between LTS lines, non-LTS minors
receive the standard 12-month support window. Teams that prefer a
slow upgrade cadence can hop LTS → LTS every 12 months and stay
inside the support window.

The non-LTS minors exist to ship features faster without forcing the
whole ecosystem onto a new line. An LTS line is **frozen** — it only
gets bug fixes, CVE patches, and doc updates. New features land on
the next non-LTS minor.

### 7. Plugin ecosystem promise

First-party plugin packages (e.g. `pylar-admin`, `pylar-stripe`,
`pylar-passport`) follow **the same SemVer rules** but track their
own versions independently of the core framework. Each plugin
publishes a compatibility matrix in its README (`pylar-admin 1.x
supports pylar 1.0 – 1.8`). The ADR-0005 entry-point mechanism means
a plugin can be picked up by a compatible core version without code
changes.

## Phasing

* **13a (this commit)**: ADR text + docs site page + a short
  machine-readable manifest listing the supported lines (added in
  a follow-up once 1.0 ships).
* **13b**: multi-tenancy (ADR-0011) — separate scope.

## Consequences

* **Adoption clarity**: prospective adopters can commit to pylar
  with a concrete expectation of what will and will not change
  under their feet.
* **Maintainer discipline**: introducing a public symbol now carries
  a support cost. We will gate new public surface through ADRs — an
  addition without an ADR is not part of the public API even if it's
  reachable, and will be allowed to disappear without a deprecation
  cycle.
* **Ecosystem stability**: plugin authors have a target to test
  against. The compatibility matrix in each plugin README is the
  primary user-facing artifact of this policy.
* **Pre-1.0 freedom**: the framework is still under active design.
  Pre-1.0 breakages will continue to land when an architectural
  lesson warrants them; the difference after this ADR is that each
  breakage is called out explicitly with a migration note rather
  than left to readers to diff the changelog.

## References

* REVIEW-3 section 6.3 — ecosystem hardening priorities.
* ADR-0001 — explicit-wiring principle informs what counts as public.
* ADR-0005 — entry-point mechanism for plugin ecosystem.
* Semantic Versioning 2.0: https://semver.org
* Django's backwards-compatibility policy:
  https://docs.djangoproject.com/en/stable/misc/api-stability/
* Laravel's release process:
  https://laravel.com/docs/releases
