# Project Structure

pylar follows a convention-over-configuration layout inspired by Laravel:

```
myapp/
├── app/                        Application code
│   ├── http/
│   │   └── controllers/        HTTP controllers (auto-wired via DI)
│   ├── models/                 SQLAlchemy models (Django-style fields)
│   ├── providers/              Service providers (register + boot lifecycle)
│   ├── observers/              Model lifecycle observers
│   └── policies/               Authorization policies
├── config/
│   ├── app.py                  Provider list + AppConfig
│   └── database.py             DatabaseConfig from env
├── database/
│   ├── migrations/             Alembic revision files (flat, no versions/)
│   └── seeds/                  Seeder classes (sorted by filename)
├── resources/
│   └── views/                  Jinja2 templates
│       └── layouts/            Base layout templates
├── routes/
│   ├── web.py                  Server-rendered HTML routes
│   └── api.py                  JSON API routes
├── storage/                    Local file storage (uploads, cache files)
├── tests/                      pytest test suite
├── .env                        Environment variables (APP_KEY, DATABASE_URL, etc.)
└── .gitignore
```

## Key conventions

- **One concept per file** — `Post` model in `app/models/post.py`, not in a monolithic `models.py`
- **Providers listed by import** — no autodiscovery, no string references
- **Migrations are flat** — `database/migrations/2026_04_09_create_posts.py`, no `versions/` subfolder
- **Seeds sorted by filename** — `01_user_seeder.py` runs before `02_post_seeder.py`
- **`env.py` and `script.py.mako` are built-in** — only drop your own copies if you need to override Alembic behaviour
