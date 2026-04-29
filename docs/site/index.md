# pylar

**Typed async Python web framework — Laravel ergonomics, Django batteries.**

pylar combines Laravel's developer experience with Python's type system. Every route, handler, DTO, job, and event is typed end-to-end. mypy catches errors at commit time, not at 3am in production.

## Why pylar?

| Feature | pylar | Django | Flask | FastAPI |
|---|---|---|---|---|
| Full type safety | :white_check_mark: mypy strict | Partial | No | Partial |
| Async-first I/O | :white_check_mark: Native | Bolt-on | No | :white_check_mark: |
| DI container | :white_check_mark: Typed | No | No | Depends |
| ORM + migrations | :white_check_mark: SA 2.0 | :white_check_mark: Own | SQLAlchemy | SQLAlchemy |
| Laravel-style DX | :white_check_mark: | No | No | No |
| Queue + jobs | :white_check_mark: Typed | Celery | Celery | None |
| Mail + notifications | :white_check_mark: | :white_check_mark: | Flask-Mail | None |

## Quick Start

```bash
pip install pylar-framework
pylar new myapp
cd myapp
pylar migrate
pylar serve
```

Open [http://localhost:8000](http://localhost:8000) — your app is running.

## What's in the box

- **22 modules** — foundation, routing, database, auth, cache, queue, mail, events, notifications, broadcasting, scheduling, i18n, views, storage, encryption, session, validation, testing, console
- **771+ tests** — mypy strict on all 226 source files
- **14 HTTP middleware** — CORS, CSRF, throttle, secure headers, request ID, tracing, encryption, logging, maintenance mode, trim strings, trust proxies
- **4 cache drivers** — Memory, File, Database, Redis
- **3 queue drivers** — Memory, Database, Redis
- **3 session stores** — Memory, File, Redis
- **S3 storage** — works with AWS, MinIO, DigitalOcean Spaces
- **27 console commands** — including 13 `make:*` generators

## License

MIT
