# Contributing to pylar-framework

## Scope

This is the public source for the `pylar-framework` package — the
typed async Python web framework. The admin SPA lives in a separate
repository: <https://github.com/pylar-foundation/pylar-admin>.

If a feature spans both packages, land the framework change first; the
admin PR can follow.

## Local Setup

Use Python 3.12 and `uv`.

```bash
uv pip install -e ".[dev,sqlite,serve,cache-redis,queue-redis,broadcast-redis,session-redis,storage-s3,otel,prometheus,sentry,tinker,i18n-yaml,mail-markdown,broadcast-pusher,webauthn]"
```

## Required Checks

Before opening a pull request:

```bash
uv run ruff check pylar tests
uv run mypy pylar
uv run pytest tests -q
```

## Engineering Rules

- Follow the ADRs in `docs/adr/` for architectural changes.
- Prefer explicit typed APIs over magic or string-based indirection.
- Do not commit generated artifacts: `dist/`, `htmlcov/`, `.coverage*`, runtime `.env*`.
- Add or update tests with every behavior change.
- Keep documentation and support/versioning statements aligned with the shipped package version.

## Commit and Pull Request Policy

Use Conventional Commits, for example:

- `feat(auth): add token rotation`
- `fix(queue): preserve retry delay`
- `docs: update support matrix`

Pull requests should include:

- a short problem statement
- tests run locally
- linked issue or ADR when the change is architectural
