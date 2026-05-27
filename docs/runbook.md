# Runbook

---

## Gold layer — initial deployment

1. Pick a target SQL Server database that contains (or is linked to) the
   source ERP `dbo` tables. The reference name in the scripts is
   `pymeconta_local` — adjust the `USE` statement in `10_e2e_dashboard.sql`
   to match your environment.
2. Connect as a user with `CREATE SCHEMA`, `CREATE TABLE`, `CREATE
   PROCEDURE`, and read access on the `dbo` source tables.
3. From SSMS or `sqlcmd`, run the scripts in numeric order:

   ```
   sqlcmd -S <server> -d <database> -E -i sql/gold/01_schema_and_logging.sql
   sqlcmd -S <server> -d <database> -E -i sql/gold/02_dim_date.sql
   sqlcmd -S <server> -d <database> -E -i sql/gold/03_enrichment_tables.sql
   sqlcmd -S <server> -d <database> -E -i sql/gold/04_seeding_procs_emp7.sql
   sqlcmd -S <server> -d <database> -E -i sql/gold/05_dimensions_refresh.sql
   sqlcmd -S <server> -d <database> -E -i sql/gold/06_1_fact_sales_weekly.sql
   sqlcmd -S <server> -d <database> -E -i sql/gold/06_2_fact_stock_weekly.sql
   sqlcmd -S <server> -d <database> -E -i sql/gold/06_3_fact_stock_movements.sql
   sqlcmd -S <server> -d <database> -E -i sql/gold/06_4_fact_transfers.sql
   sqlcmd -S <server> -d <database> -E -i sql/gold/07_analytical_views.sql
   sqlcmd -S <server> -d <database> -E -i sql/gold/08_master_orchestrator.sql
   sqlcmd -S <server> -d <database> -E -i sql/gold/09_validations.sql
   ```

4. Open `sql/gold/10_e2e_dashboard.sql` in SSMS and execute it. Confirm
   the validations grid shows **16 PASS / 2 WARN / 0 FAIL** (the two
   WARN are expected for the POC profile).

---

## Gold layer — nightly refresh

A single call per tenant rebuilds the whole pipeline:

```sql
DECLARE @bid UNIQUEIDENTIFIER;
EXEC gold.sp_refresh_all @tenant_id = <id>, @batch_id = @bid OUTPUT;
SELECT @bid AS batch_id;
```

Then validate:

```sql
EXEC gold.sp_run_validations @tenant_id = <id>;
```

Any row with `status = 'FAIL'` should block downstream consumers from
trusting the snapshot. Investigate using:

```sql
SELECT step_name, status, error_msg, DATEDIFF(MS, started_at, finished_at) AS ms
  FROM gold.etl_batch_log WHERE batch_id = @bid ORDER BY id;

SELECT * FROM gold.etl_data_quality_metrics WHERE batch_id = @bid;
```

---

## Adding a new tenant

1. Decide tenant id (must exist in `dbo.empresa`).
2. Write equivalent seed procs to `04_seeding_procs_emp7.sql`:
   - `sp_seed_brand_mapping_<alias>` — brand heuristic for that tenant
   - `sp_seed_store_classification_<alias>` — warehouse → retail/depot
   - `sp_seed_business_rules_<alias>` — coverage / obsolescence rules
   - `sp_seed_society_mapping_<alias>` — legal entity name
3. Update `gold.sp_refresh_all` to call the new seeds inside an
   `IF @tenant_id = <new_id>` branch (or remove the guard if you wire
   self-discovery).
4. Run `EXEC gold.sp_refresh_all @tenant_id = <new id>, @batch_id = NULL OUTPUT;`.
5. Validate with `sp_run_validations`; cross-checks 9.6/9.7 must be 0.
6. Create a JWT for the new tenant (see [API — mint a token](#api--mint-a-token)).

---

## API — deploy

### Prerequisites

- Python 3.11+
- Microsoft ODBC Driver 17 (or 18) for SQL Server installed on the API host
- SQL Server accessible from the API host
- `ANTHROPIC_API_KEY` obtained from the Anthropic console

### Steps

```bash
cd api

# Install dependencies
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -e ".[dev]"

# Configure
cp .env.example .env
# Edit .env — at minimum set:
#   ANTHROPIC_API_KEY=sk-ant-...
#   SQL_PASSWORD=<your password>
#   JWT_SECRET=<random 32-byte hex>
#   AUTH_REQUIRE_JWT=true         # disable mock headers in production
#   LOG_JSON=true                 # structured logs for log aggregation

# Create the audit schema (one-time per database)
sqlcmd -S <server> -d <database> -U sa -P <password> \
  -i scripts/setup_audit_schema.sql

# Start the server (single worker for now; swap to gunicorn for prod)
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

Verify the server is up:

```bash
curl http://localhost:8000/api/v1/health
# Expected: {"status": "ok", "db_ok": true, ...}
```

---

## API — mint a token

Generate a JWT for testing or onboarding a user:

```bash
cd api
python - <<'EOF'
from app.auth.jwt_handler import create_access_token
# Adjust user_id, tenant_id and role as needed
token = create_access_token(user_id="alice", tenant_id=7, role="direccion")
print(token)
EOF
```

Valid roles: `direccion` · `marca` · `tienda` · `sku`

The token expires in `JWT_EXPIRE_MINUTES` (default 60). Tokens are signed with `JWT_SECRET` — rotating the secret invalidates all existing tokens.

---

## API — rotate JWT_SECRET

Changing `JWT_SECRET` immediately invalidates all issued tokens. All users must re-authenticate.

1. Generate a new secret:
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
2. Update `JWT_SECRET` in `.env` (or the deployment secrets store).
3. Restart the API process.
4. Inform users that existing tokens are invalid and provide new ones.

---

## API — investigate via audit log

Every request writes a row to `api_audit.ai_audit_log`. Query it directly on SQL Server:

```sql
-- Most recent requests for a tenant
SELECT request_id, user_id, user_role, status, cost_usd,
       tokens_input, tokens_output, duration_ms, created_at
  FROM api_audit.ai_audit_log
 WHERE tenant_id = 7
 ORDER BY created_at DESC;

-- Full detail for a specific request
SELECT *
  FROM api_audit.ai_audit_log
 WHERE request_id = CAST('<uuid>' AS UNIQUEIDENTIFIER);

-- Tool invocations for a request
SELECT JSON_VALUE(value, '$.name') AS tool_name,
       JSON_VALUE(value, '$.duration_ms') AS duration_ms,
       JSON_VALUE(value, '$.is_error') AS is_error
  FROM api_audit.ai_audit_log
 CROSS APPLY OPENJSON(tools_invoked)
 WHERE request_id = CAST('<uuid>' AS UNIQUEIDENTIFIER);

-- Error requests in the last 24 hours
SELECT request_id, user_id, status, error_msg, created_at
  FROM api_audit.ai_audit_log
 WHERE tenant_id = 7
   AND status = 'ERROR'
   AND created_at >= DATEADD(HOUR, -24, GETUTCDATE())
 ORDER BY created_at DESC;

-- Cost summary by day
SELECT CAST(created_at AS DATE) AS day,
       COUNT(*) AS requests,
       SUM(tokens_input) AS total_tokens_in,
       SUM(tokens_output) AS total_tokens_out,
       SUM(CAST(cost_usd AS FLOAT)) AS total_cost_usd
  FROM api_audit.ai_audit_log
 WHERE tenant_id = 7
 GROUP BY CAST(created_at AS DATE)
 ORDER BY day DESC;
```

Alternatively, a `direccion` user can retrieve an individual audit row via the chat interface by asking Claude to call `get_audit_trail(request_id="<uuid>")`.

---

## API — adjust rate limits

Rate limits are read from environment variables at startup. To change them:

1. Update the relevant variable(s) in `.env`:

   ```env
   RATE_LIMIT_TENANT_HOUR=200      # requests per hour per tenant
   RATE_LIMIT_USER_HOUR=50         # requests per hour per user
   RATE_LIMIT_TOKENS_DAY=2000000   # tokens per 24h per tenant
   ```

2. Restart the API process.

Note: counters are in-memory and reset on restart. For multi-worker or multi-instance deployments, the in-memory limiter is per-process — swap to a Redis-backed implementation before scaling horizontally.

---

## Gold layer — common failure modes

| Symptom | Likely cause | Fix |
|---|---|---|
| `RAISERROR: No se pudo resolver el rango` in `sp_refresh_fact_*_weekly` | `dim_date` doesn't cover the requested window | Run `EXEC gold.sp_populate_dim_date '<from>', '<to>'`. The master orchestrator extends automatically. |
| Cross-check 9.6 fails by a small amount | Currency conversion drift — `documento.tasa_cambio` changed retroactively | Re-run the master refresh; sales are window-based, so a full re-load picks up new rates. |
| Cross-check 9.7 fails | Source kardex was recomputed by `SP_U_SUBMAYOR_INVENTARIO` after our incremental movement load | `EXEC gold.sp_refresh_fact_stock_movements @tenant_id = <id>, @full_refresh = 1`, then re-validate. |
| `gold.dim_sku` shows 0 SKUs after refresh | Tenant has no rows in `dbo.producto` with `[delete] = 0` | Check the source ERP; verify tenant id. |
| New tenant: `sp_refresh_all` succeeds but `vw_brand_performance` shows everything as `SIN MARCA` | Seed procs for that tenant haven't been written / executed | Write `sp_seed_brand_mapping_<alias>` and run it before re-refresh. |
| `vw_active_alerts` empty for a tenant with stock issues | `dim_business_rules` empty for that tenant | Seed business rules with `sp_seed_business_rules_<alias>`. Defaults: cov_min=30, cov_max=90, obsolete=90 days. |

---

## API — common failure modes

| Symptom | HTTP status | Fix |
|---|---|---|
| `{"status": "degraded", "db_ok": false}` from `/health` | — | Check SQL Server connectivity and credentials in `.env` |
| `503: ANTHROPIC_API_KEY not set or is a placeholder` | 503 | Set a valid `ANTHROPIC_API_KEY` in `.env` and restart |
| `401: missing_bearer_token` | 401 | `AUTH_REQUIRE_JWT=true` is set; provide a valid Bearer token |
| `401: invalid_token: Signature has expired` | 401 | Mint a new token (see [mint a token](#api--mint-a-token)) |
| `429: scope=tenant` | 429 | Tenant hit the hourly request cap; raise `RATE_LIMIT_TENANT_HOUR` or wait |
| `429: scope=tokens` | 429 | Tenant hit the daily token budget; raise `RATE_LIMIT_TOKENS_DAY` or wait for midnight UTC |
| `500: internal_error` | 500 | Check structured logs and `api_audit.ai_audit_log` for `status='ERROR'` rows |

---

## Performance notes

### Gold layer

- POC tenant: full pipeline runs in **<1 second** (100 SKUs, 4 stores,
  ~2.4k kardex rows, ~38 weeks).
- For a tenant in the 10k SKU × 50 store × 250 week range, expect
  `fact_stock_weekly` to dominate (`OUTER APPLY` against the kardex per
  (week, pair)). Mitigations available before considering partitioning:
  - Tighten the dead-pair threshold (`@dead_threshold_days`).
  - Narrow the refresh window (default is from first ever document).
  - Add a covering index on `submayor_inventario(id_almacen_producto,
    id_documento)` if absent in your source DB.

### API

- The connection pool is 10 connections (configurable via `SQL_POOL_SIZE`). Each tool call occupies one connection for the duration of the query.
- `asyncio.to_thread` keeps the event loop free while SQL is executing, but the pool becomes the bottleneck under heavy concurrency.
- The in-memory rate limiter is O(window-size) per call and holds a single `threading.Lock`. It is not a bottleneck in practice for single-worker deployments.

---

## Safety

- All Gold tables are scoped by `tenant_id` and every refresh proc filters on `@tenant_id`. No tenant-leak in either direction.
- Source tables are **read-only** from this pipeline. We never `INSERT`, `UPDATE` or `DELETE` against `dbo.*`.
- Log and DQ tables grow without bound. Trim by `batch_id` age in production (not done by these scripts).
- The API enforces `tenant_id` from the JWT claim only. It is never read from the request body.
- `AUTH_REQUIRE_JWT=true` must be set in production to disable the mock-header fallback.
- Never commit `ANTHROPIC_API_KEY`, `SQL_PASSWORD`, or `JWT_SECRET` to version control. All three are gitignored via `.env`.
