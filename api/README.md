# `api/` — Retail AI Platform backend

FastAPI service that exposes the Gold data warehouse as Claude-callable
tools. Phase 4 of the retail-ai-platform project.

## Status (Sub-phase 4.1)

- Project scaffolding, settings, structured logging.
- SQL Server connection pool (`pyodbc` + `asyncio.to_thread`).
- `GET /api/v1/health` with real DB probe.
- `api_audit` schema (audit log + conversation + sanitiser token map).

Coming next: tools (4.2), orchestrator + `/chat` (4.3), remaining tools
(4.4), JWT + rate limit + audit persist (4.5), docs (4.6).

## Requirements

- Python 3.11+
- Microsoft ODBC Driver for SQL Server 17 (or 18, adjust `.env`)
- SQL Server with both schemas:
  - `[gold]` — see `../sql/gold/`
  - `[api_audit]` — run `scripts/setup_audit_schema.sql`

## Quick start

```bash
cd api

# Create venv + install deps
python -m venv .venv
.venv/Scripts/activate            # Windows
# source .venv/bin/activate       # macOS/Linux
pip install -e ".[dev]"

# Configure
cp .env.example .env
# edit .env with your local SQL Server credentials

# Create audit schema (one-time)
sqlcmd -S <server> -d <database> -U sa -P <pwd> -i scripts/setup_audit_schema.sql

# Smoke test
pytest -q

# Run dev server
uvicorn app.main:app --reload
curl http://localhost:8000/api/v1/health
```

Expected `/health` response:

```json
{
  "status": "ok",
  "db_ok": true,
  "db_database": "pymeconta_local",
  "tenant_count": 12
}
```

## Project layout

```
api/
├── pyproject.toml
├── .env.example            -- template (real .env is gitignored)
├── app/
│   ├── main.py             -- FastAPI + structlog + lifespan
│   ├── config.py           -- pydantic-settings (env-driven)
│   ├── db/
│   │   └── connection.py   -- pyodbc pool + async execute_query/ping
│   └── api/
│       ├── router.py       -- mounts /api/v1
│       └── v1/
│           └── health.py
├── scripts/
│   └── setup_audit_schema.sql
└── tests/
    ├── conftest.py
    └── test_health.py
```

## Design notes

- **Multi-tenant safety**: all later queries against `[gold]` MUST scope
  by `tenant_id` extracted from the JWT (never from the request body).
  The connection pool itself is tenant-agnostic; isolation is at the
  query layer.
- **Sync driver inside async stack**: `pyodbc` is sync. Calls go through
  `asyncio.to_thread` so the FastAPI event loop stays free. Pool of 10
  connections (configurable). Swap to `aioodbc` later if needed.
- **Audit schema is separate** from `[gold]`. The Gold schema is the
  analytical data warehouse; `api_audit` is operational metadata. Don't
  mix lifecycles.
