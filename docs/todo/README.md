# Backlog

Per-module follow-up notes captured during the build. Each entry is a
deferred design decision or feature that we explicitly **did not** ship
in the current iteration of the corresponding module — keeping them
out of the source tree as TODO comments and out of the issue tracker
keeps the rationale for the deferral close to the architectural prose.

| File | Module |
|---|---|
| [`routing.md`](routing.md) | `pylar/routing/` |
| [`console.md`](console.md) | `pylar/console/` |
| [`database.md`](database.md) | `pylar/database/` |
| [`database-migrations.md`](database-migrations.md) | `pylar/database/migrations/` |
| [`validation.md`](validation.md) | `pylar/validation/` |
| [`auth.md`](auth.md) | `pylar/auth/` |
| [`events.md`](events.md) | `pylar/events/` |
| [`queue.md`](queue.md) | `pylar/queue/` |
| [`cache.md`](cache.md) | `pylar/cache/` |
| [`storage.md`](storage.md) | `pylar/storage/` |
| [`scheduling.md`](scheduling.md) | `pylar/scheduling/` |
| [`views.md`](views.md) | `pylar/views/` |
| [`mail.md`](mail.md) | `pylar/mail/` |
| [`notifications.md`](notifications.md) | `pylar/notifications/` |
| [`broadcasting.md`](broadcasting.md) | `pylar/broadcasting/` |
| [`i18n.md`](i18n.md) | `pylar/i18n/` |
| [`testing.md`](testing.md) | `pylar/testing/` |

When a backlog item is picked up, delete its entry from the relevant
file rather than marking it complete — these files are a list of
*open* questions, not a changelog.
