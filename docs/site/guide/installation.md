# Installation

## Requirements

- Python 3.12+
- pip or uv

## Install

```bash
pip install pylar
```

### With extras

```bash
# PostgreSQL
pip install 'pylar[postgres]'

# Redis (cache + session + queue + broadcast)
pip install 'pylar[cache-redis,session-redis,queue-redis,broadcast-redis]'

# S3 storage (AWS, MinIO, DO Spaces)
pip install 'pylar[storage-s3]'

# Argon2 password hashing
pip install 'pylar[auth]'

# OpenTelemetry tracing
pip install 'pylar[tracing]'

# Development tools
pip install 'pylar[dev]'

# Everything
pip install 'pylar[dev,postgres,cache-redis,session-redis,queue-redis,storage-s3,auth,tracing,serve]'
```

## Create a project

```bash
pylar new myapp
cd myapp
```

This generates:

```
myapp/
├── app/
│   ├── http/controllers/
│   ├── models/
│   ├── providers/
│   │   ├── app_service_provider.py
│   │   └── route_service_provider.py
│   ├── observers/
│   └── policies/
├── config/
│   ├── app.py
│   └── database.py
├── database/
│   ├── migrations/
│   └── seeds/
├── resources/views/
│   ├── layouts/app.html
│   └── home.html
├── routes/
│   ├── web.py
│   └── api.py
├── tests/
├── .env          ← auto-generated APP_KEY + SESSION_SECRET
└── .gitignore
```

## Run

```bash
pylar migrate
pylar serve
```

Open [http://localhost:8000](http://localhost:8000).
