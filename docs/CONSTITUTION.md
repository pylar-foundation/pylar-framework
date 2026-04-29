# Pylar Framework Constitution

This document distills the **load-bearing rules** every ADR builds on.
Read it before proposing architectural changes, before writing a new
ADR, and before pushing code that touches the framework core.

Each rule links back to the ADR that established it. The Constitution
itself does not supersede ADRs — it's a terse index of the stable
commitments that every ADR has assumed and that every future ADR is
expected to respect. A new decision that contradicts a rule here
must either (a) revise the rule in a dedicated ADR or (b) be
rejected.

## I. Language and typing

1. **Python 3.12 is the floor.** Every framework module and every
   example project targets Python 3.12 features (PEP 695 generics,
   `type` statement, structural pattern matching). *[ADR-0003]*
2. **Strict mypy is mandatory** for the `pylar/` package.
   `disallow_untyped_defs`, `disallow_any_generics`, `strict_optional`
   are non-negotiable. Example projects and tests may relax this
   locally. *[ADR-0001]*
3. **No `**kwargs` in public APIs.** The container refuses to wire
   anything with variadic keyword arguments. Internal helpers that
   take `params: dict[str, object]` are not the same as `**kwargs`. *[ADR-0001]*
4. **No string class identifiers.** Always import the class. Patterns
   like `"app.models.User"` in config are banned. *[ADR-0001]*
5. **No facades, no global helpers, no magic `__getattr__`.** They
   break the type system. *[ADR-0001]*

## II. Async and I/O

6. **Every I/O surface is `async def`.** Sync code is allowed only
   where async makes no sense (CLI bootstrap, Alembic entry points,
   the cron expression matcher). *[ADR-0001]*
7. **Sync libraries are wrapped via `asyncio.to_thread`.** The outer
   surface stays async. *[ADR-0003]*

## III. Contracts, container, providers

8. **Protocols over ABCs** for contracts that have multiple
   implementations (drivers). Use `typing.Protocol` + explicit
   `@runtime_checkable` where duck-typed validation is needed. *[ADR-0001]*
9. **Typed IoC container.** Bindings are keyed by `type[T]`. Three
   lifetimes: `TRANSIENT` (default), `SINGLETON`, `SCOPED`. The
   container refuses to auto-wire any constructor that lacks type
   hints. *[ADR-0001]*
10. **Service providers ship in pairs**: sync `register` (bindings
    only, no I/O) and async `boot` (side effects allowed). `boot`
    can assume every `register` in the application has already run,
    so providers can reference each other regardless of declaration
    order. *[ADR-0001, ADR-0002]*
11. **First-party providers are explicit.** User projects list their
    providers in `config/app.py`. Third-party plugin packages install
    via entry points under the `pylar.providers` group and are
    auto-discovered on boot unless `autodiscover=False`. *[ADR-0005]*

## IV. Project layout

12. **Laravel directory convention.** Every pylar project has
    `app/`, `config/`, `database/migrations/`, `database/seeds/`,
    `routes/`, `resources/views/`, `tests/`, `storage/`, `.env`,
    and one `config/app.py` that exports `config = AppConfig(...)`. *[ADR-0002]*
13. **Inside `pylar/` every module has the same shape.**
    `__init__.py` re-exports only; `exceptions.py` with a single
    `*Error` base; focused files (one concept per file); a
    `provider.py`; optional `drivers/` subpackage when the module
    exposes a Protocol with multiple implementations. *[ADR-0002]*
14. **No code duplication.** If two places need the same logic,
    extract it into a shared function. When a command needs the
    behaviour of another command, it instantiates and calls it
    rather than copying the body. *[ADR-0001]*

## V. Errors and HTTP

15. **`ValidationError` renders as 422, `AuthorizationError` as 403.**
    Both paths are symmetric, both live in `pylar/routing/compiler.py`.
    Add new global error handlers in the same place rather than
    installing Starlette exception middleware on your own. *[ADR-0001]*
16. **Browser clients get styled HTML error pages; JSON clients get
    a structured `{"message", "code"}` envelope.** Content
    negotiation happens once in the framework and is not repeated
    at the controller level. *[ADR-0001]*

## VI. Database and migrations

17. **SQLAlchemy 2.0 typed mapping** is the canonical ORM. Pylar
    exposes a Manager / QuerySet layer on top — pylar does not
    hide SA, it provides ergonomic defaults. *[ADR-0003]*
18. **Alembic is the migration engine.** Every framework module
    that ships a table also ships a migration stub; user projects
    copy the stub into `database/migrations/`. *[ADR-0003]*
19. **Migration stubs are named with a canonical timestamp** —
    `YYYY_MM_DD_HHMMSS_<name>.py.stub`. The timestamp reflects the
    stub's revision position so that `ls` of a `database/migrations/`
    directory sorts identically to the Alembic revision chain.
    **`pylar new` copies each stub verbatim** (strips only the
    `.stub` suffix), preserving both the filename and the revision
    header unchanged. Projects that add their own migrations chain
    them *after* the last system revision so shared stubs stay
    deterministic across installations.
20. **`DatabaseSessionMiddleware` does not auto-commit.** Write
    paths wrap in `async with pylar.database.transaction(): ...`.
    Implicit commit-on-2xx is deliberately avoided to keep failure
    modes visible. *[ADR-0001]*

## VII. Testing

21. **`pytest-asyncio` in `auto` mode.** Every `async def` test is
    recognised automatically; do not add `@pytest.mark.asyncio`. *[ADR-0001]*
22. **Database tests use `sqlite+aiosqlite:///:memory:`** via
    shared conftest fixtures. HTTP tests drive the kernel via
    `httpx.ASGITransport` — no real server, no uvicorn.*[ADR-0001]*
23. **Integration tests hit real infrastructure.** When a test
    covers behaviour that depends on a driver (Redis queue, S3
    storage, PG-specific SQL) it must run against that driver in
    CI, not a mock.

## VIII. Versioning and release

24. **SemVer post-1.0.** Patch is bug fixes, minor is additive,
    major may break — and ships a migration guide. *[ADR-0010]*
25. **Public API is everything in a module's `__all__`** plus every
    symbol re-exported at its top-level `__init__`. Names starting
    with `_`, deep-imported submodules, and internal plumbing are
    out of contract. *[ADR-0010]*
26. **Pre-1.0 is explicit.** The currently published line is a
    release candidate; pin exact versions and expect minors to
    break with a migration note in the changelog. *[ADR-0010]*
27. **Security fixes backport to every supported line.** Initial
    acknowledgement within 3 business days, fix timing by severity. *[ADR-0010]*

## IX. ADR process

28. **Every architectural change gets an ADR.** ADRs are numbered
    sequentially in `docs/adr/`. They are the source of truth for
    *why* the codebase looks the way it does — git history is the
    record of *what* changed, ADRs are the record of *why*.
29. **ADRs are immutable once accepted.** A decision that supersedes
    an earlier one lands as a new ADR with a `## Supersedes ADR-XXXX`
    header. Do not edit historical ADRs beyond typo fixes.
30. **The Constitution indexes rules, it does not introduce them.**
    Before adding a rule here, make sure the ADR it belongs to has
    been written or updated.

## X. Documentation

31. **Every public class / function has a docstring** that explains
    both *what* it does and *why* it's shaped that way. Rationale
    is the important half. *[ADR-0001]*
32. **User-facing docs live in `docs/site/`** (MkDocs). Architectural
    docs live in `docs/adr/`. Backlog / deferred work lives in
    `docs/todo/`. No cross-mixing. *[ADR-0002]*
33. **MkDocs must pass `--strict`** at every commit that touches the
    site. Broken links and unresolved anchors block merge.

---

This Constitution is maintained by the framework core team.
Amendments require either (a) a new ADR that adds / modifies a rule,
or (b) a housekeeping PR that reconciles wording with an existing
ADR whose rules drifted from this index.
