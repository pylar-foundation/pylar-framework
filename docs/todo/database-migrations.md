# database/migrations/ — backlog

The completeness batch landed `migrate:fresh`, `migrate:reset`,
`db:seed`, and `--pretend` flags on `migrate` / `migrate:rollback`.
What is still on the wishlist:

## Async-native Alembic

Today the runner converts the user's async DSN to a synchronous driver
because Alembic itself is sync. This forces installations to depend on
`psycopg2` even if production uses `asyncpg`. Once Alembic's async
support is mature enough, switch the env.py template to use
`engine.run_sync()` and drop the URL conversion entirely.

## `migrate:install`

Explicit "create the migrations directory and the env.py template"
command. Today the runner scaffolds them lazily on the first call,
which is fine but means there is no obvious "set up migrations" step
in the user's workflow. Worth adding when a project asks for it.

## Squash old migrations

Laravel's `migrate:squash` command consolidates the migration history
up to a chosen point into a single file, so long-lived projects do
not have to apply hundreds of revisions on a fresh checkout. Alembic
exposes the building blocks via `revision --splice`; needs design
work to expose them through a single pylar command.
