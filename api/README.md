# Retail AI Platform — API

![Tests](https://img.shields.io/badge/tests-204%20passed-brightgreen)
![Python](https://img.shields.io/badge/python-3.13-blue)
![Phase](https://img.shields.io/badge/phase-5.4%20complete-success)

FastAPI service that turns the Gold data warehouse into a Claude-powered conversation interface. The API exposes fifteen analytical tools (alerts, dashboards, SKU analysis, period comparison, audit trail, monthly periodicity, and composite weekly briefings) via Anthropic's function-calling protocol and wraps every request with JWT auth, bi-directional data sanitization, in-memory rate limiting, and a full audit trail persisted in SQL Server.

The architecture is intentionally single-layer: Claude selects and invokes the tools in the right order, accumulates facts across multiple calls within one conversation, and composes a natural-language answer. The API enforces tenant isolation at every layer — auth claims, SQL `WHERE tenant_id`, and the sanitizer token map are all scoped per tenant.

Sub-fase 5.4 is complete: 204 tests pass, 15 tools, 4 role prompts, bounded 3-turn conversational memory, and a full eval framework (20-question catalog, runner, metrics comparator, text/JSON reports, CLI).

---

## Quick start

```bash
cd api

# Create virtual environment and install dependencies
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -e ".[dev]"

# Configure (copy template, fill in SQL credentials and API key)
cp .env.example .env
# Edit .env — set SQL_PASSWORD and ANTHROPIC_API_KEY at minimum

# Create the audit schema (one-time per database)
sqlcmd -S <server> -d <database> -U sa -P <password> -i scripts/setup_audit_schema.sql

# Run the test suite
pytest -q

# Start the development server
uvicorn app.main:app --reload
```

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | _(required)_ | Anthropic API key — never commit this |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-6` | LLM model name |
| `SQL_SERVER` | `localhost` | SQL Server host |
| `SQL_DATABASE` | `pymeconta_local` | Database name |
| `SQL_USER` | `sa` | SQL Server login |
| `SQL_PASSWORD` | _(required)_ | SQL Server password — never commit this |
| `SQL_DRIVER` | `{ODBC Driver 17 for SQL Server}` | ODBC driver string |
| `SQL_POOL_SIZE` | `10` | Connection pool size |
| `JWT_SECRET` | `change-me-in-production` | HS256 signing key — rotate in prod |
| `JWT_ALGORITHM` | `HS256` | JWT algorithm |
| `JWT_EXPIRE_MINUTES` | `60` | Token lifetime |
| `AUTH_REQUIRE_JWT` | `false` | Set `true` in production to disable mock headers |
| `LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` |
| `LOG_JSON` | `false` | Emit structured JSON logs (set `true` in production) |
| `RATE_LIMIT_TENANT_HOUR` | `100` | Max requests per hour per tenant |
| `RATE_LIMIT_USER_HOUR` | `30` | Max requests per hour per user |
| `RATE_LIMIT_TOKENS_DAY` | `1000000` | Max tokens per day per tenant |
| `MEMORY_TURNS_PER_REQUEST` | `3` | User+assistant pairs loaded per chat request |

---

## API requests

### Health check

```bash
curl http://localhost:8000/api/v1/health
```

```json
{
  "status": "ok",
  "db_ok": true,
  "db_database": "pymeconta_local",
  "tenant_count": 12
}
```

### Chat — mock auth (dev only, `AUTH_REQUIRE_JWT=false`)

```bash
curl -s -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -H "X-Mock-Tenant: 7" \
  -H "X-Mock-Role: direccion" \
  -d '{"message": "¿Cuál es el resumen ejecutivo de esta semana?"}' | python -m json.tool
```

### Mint a JWT for testing

```bash
cd api
python - <<'EOF'
from app.auth.jwt_handler import create_access_token
token = create_access_token(user_id="alice", tenant_id=7, role="direccion")
print(token)
EOF
```

### Chat — real JWT (Bearer header)

```bash
TOKEN=$(python -c "
from app.auth.jwt_handler import create_access_token
print(create_access_token(user_id='alice', tenant_id=7, role='direccion'))
")

curl -s -X POST http://localhost:8000/api/v1/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "¿Cuáles son las alertas de alto impacto?"}'
```

### Continue an existing conversation

```bash
curl -s -X POST http://localhost:8000/api/v1/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "¿Y las marcas debajo del plan?", "conversation_id": "<uuid-from-prev-response>"}'
```

### Marca role (sanitizer active — entity IDs replaced with opaque tokens)

```bash
curl -s -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -H "X-Mock-Tenant: 7" \
  -H "X-Mock-Role: marca" \
  -d '{"message": "Muéstrame el rendimiento por marca esta semana"}'
```

**Monthly summary (latest month)**

```bash
curl -s -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -H "X-Mock-Tenant: 7" \
  -d '{"message": "Dame el resumen de abril 2026"}' | jq .response
```

**Monthly period comparison**

```bash
curl -s -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -H "X-Mock-Tenant: 7" \
  -d '{"message": "Compará abril vs marzo en facturación"}' | jq .response
```

**Executive monthly briefing (direccion only)**

```bash
curl -s -X POST http://localhost:8000/api/v1/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "Necesito el informe ejecutivo de mayo 2026"}' | jq .response
```

---

## CLI tool runner

The CLI lets you call any tool directly without starting the server or invoking Claude. Useful for debugging queries and verifying data without LLM overhead.

```bash
cd api

# Active alerts, high severity only
python -m app.tools.cli get_active_alerts --tenant 7 --severity HIGH --limit 5 --pretty

# Store dashboard — all stores
python -m app.tools.cli get_store_dashboard --tenant 7 --pretty

# Brand performance — single brand
python -m app.tools.cli get_brand_performance --tenant 7 --brand-id 1 --pretty

# Executive summary (latest week)
python -m app.tools.cli get_executive_summary --tenant 7 --pretty

# SKU detail — single SKU across all stores
python -m app.tools.cli get_sku_detail --tenant 7 --sku-id 7 --pretty

# SKU coverage — red items only
python -m app.tools.cli get_sku_coverage_status --tenant 7 --status RED --limit 5 --pretty

# Velocity segmentation — fast movers
python -m app.tools.cli get_velocity_segmentation --tenant 7 --segment A --pretty

# Recommended actions
python -m app.tools.cli get_action_recommendations --tenant 7 --limit 5 --pretty

# Period comparison (weekly — default)
python -m app.tools.cli compare_periods --tenant 7 \
  --metric revenue_net --period-a 2026-W18 --period-b 2026-W19 --scope brand --pretty

# Period comparison (monthly)
python -m app.tools.cli compare_periods --tenant 7 \
  --period-type month --period-a 2026-04 --period-b 2026-03 --metric revenue_net --pretty

# Monthly summary (latest month)
python -m app.tools.cli get_monthly_summary --tenant 7 --pretty

# Monthly summary (specific month + brand scope)
python -m app.tools.cli get_monthly_summary --tenant 7 --year-month 2026-04 --scope brand:5 --pretty

# Monthly executive briefing (direccion only)
python -m app.tools.cli get_monthly_executive_briefing --tenant 7 --role direccion --pretty

# Executive weekly briefing (composite — saves ~4 LLM iterations)
python -m app.tools.cli get_executive_weekly_briefing --tenant 7 --role direccion --pretty

# Store daily briefing
python -m app.tools.cli get_store_daily_briefing --tenant 7 --role tienda --store-id 1 --pretty

# Brand weekly review
python -m app.tools.cli get_brand_weekly_review --tenant 7 --role marca --brand-id 1 --pretty

# Audit trail (direccion role required)
python -m app.tools.cli get_audit_trail --tenant 7 --role direccion \
  --request-id <uuid> --pretty
```

---

## Eval framework

The eval framework measures LLM quality without touching the Anthropic API in CI. It runs a 20-question catalog (5 per role) against a real tenant and scores each response on tool selection and concept coverage.

```bash
# Run all 20 questions against tenant 9001 (synthetic data)
python -m app.evaluation.cli run --tenant 9001 --text

# Run direccion questions only, save JSON artifact
python -m app.evaluation.cli run --tenant 9001 --role direccion --output run_a.json

# Run specific questions
python -m app.evaluation.cli run --tenant 9001 --ids Q01,Q06,Q11 --text

# Compare two runs (detect regressions after a prompt change)
python -m app.evaluation.cli compare run_a.json run_b.json
```

Output metrics:
- **tool_hit_rate** — % of questions where at least one expected tool was invoked
- **concept_coverage** — % of expected Spanish concepts found in the response
- **success_rate** — % of questions completed without errors
- **by_role** — per-role breakdown of all metrics

---

## Tests

```bash
# All tests (quiet)
pytest -q

# All tests with coverage
pytest --cov=app --cov-report=term-missing -q

# Specific module
pytest tests/test_tools/test_alerts.py -v

# Security tests only
pytest tests/test_security/ -v

# Audit tests only
pytest tests/test_audit/ -v
```

---

## Project layout

```
api/
├── pyproject.toml
├── .env.example              -- env template (real .env is gitignored)
├── scripts/
│   └── setup_audit_schema.sql  -- creates api_audit schema (run once)
├── app/
│   ├── main.py               -- FastAPI app + structlog + lifespan pool
│   ├── config.py             -- pydantic-settings (all env vars)
│   ├── auth/
│   │   ├── jwt_handler.py    -- create_access_token / decode_access_token
│   │   └── dependencies.py   -- get_auth_context (JWT → mock headers → defaults)
│   ├── db/
│   │   ├── connection.py     -- pyodbc pool + execute_query / ping
│   │   ├── queries.py        -- all SQL SELECT functions (tenant-scoped)
│   │   └── conversation.py   -- multi-turn conversation persistence
│   ├── tools/
│   │   ├── __init__.py       -- TOOL_REGISTRY + anthropic_tools(role)
│   │   ├── schemas.py        -- shared enums + pydantic_to_anthropic_tool
│   │   ├── alerts.py         -- get_active_alerts
│   │   ├── store.py          -- get_store_dashboard
│   │   ├── brand.py          -- get_brand_performance
│   │   ├── executive.py      -- get_executive_summary (composite)
│   │   ├── sku.py            -- get_sku_detail + get_sku_coverage_status
│   │   ├── velocity.py       -- get_velocity_segmentation
│   │   ├── recommendations.py -- get_action_recommendations
│   │   ├── compare.py        -- compare_periods (week + month modes)
│   │   ├── audit.py          -- get_audit_trail (direccion only)
│   │   ├── monthly.py        -- get_monthly_summary (direccion, marca)
│   │   ├── composite.py      -- get_monthly_executive_briefing (direccion)
│   │   ├── briefings.py      -- get_executive_weekly_briefing + get_store_daily_briefing + get_brand_weekly_review
│   │   └── cli.py            -- python -m app.tools.cli
│   ├── llm/
│   │   ├── claude_client.py  -- AsyncAnthropic factory
│   │   ├── orchestrator.py   -- tool-calling loop → ConversationResult
│   │   ├── tool_dispatcher.py -- role gate + Pydantic validation + execution
│   │   └── prompts/
│   │       ├── generic.py    -- GENERIC_SYSTEM_PROMPT (fallback)
│   │       ├── direccion.py  -- DIRECCION_SYSTEM_PROMPT
│   │       ├── marca.py      -- MARCA_SYSTEM_PROMPT
│   │       ├── tienda.py     -- TIENDA_SYSTEM_PROMPT
│   │       ├── sku.py        -- SKU_SYSTEM_PROMPT
│   │       └── selector.py   -- select_prompt(role) → str
│   ├── security/
│   │   ├── sanitizer.py      -- tokenize_payload / detokenize_text
│   │   └── rate_limiter.py   -- sliding-window limiter + module singleton
│   ├── audit/
│   │   └── persister.py      -- persist_audit_row / estimate_cost_usd / hash_text
│   └── api/
│       ├── router.py         -- mounts /api/v1
│       └── v1/
│           ├── health.py         -- GET /api/v1/health
│           ├── chat.py           -- POST /api/v1/chat (full pipeline)
│           └── conversations.py  -- GET /api/v1/conversations/{id} (summary)
├── evaluation/
│   ├── catalog.py    -- 20-question eval catalog (5 per role)
│   ├── runner.py     -- EvalRunner + QuestionResult + EvalRun
│   ├── metrics.py    -- compute_metrics (tool_hit_rate, concept_coverage, by_role)
│   ├── comparator.py -- compare_runs → RunComparison (regressions / improvements)
│   ├── report.py     -- render_json + render_text (✓/✗ per-question table)
│   └── cli.py        -- python -m app.evaluation.cli run / compare
└── tests/
    ├── conftest.py           -- TestClient fixture + reset_rate_limiter autouse
    ├── test_health.py
    ├── test_chat_endpoint.py
    ├── test_tools/
    ├── test_llm/
    ├── test_security/
    ├── test_audit/
    ├── test_db/
    └── test_evaluation/
```

---

## Architecture

```
HTTP client
    │
    ▼
┌────────────────────────────────────────────────────────────┐
│  FastAPI  (uvicorn)                                        │
│                                                            │
│  GET /api/v1/health ──► DB ping                            │
│                                                            │
│  POST /api/v1/chat                                         │
│    │                                                       │
│    ├─ 1. Auth: Bearer JWT → AuthContext(user, tenant, role)│
│    ├─ 2. Rate limit (tenant/h · user/h · tokens/day)       │
│    ├─ 3. Conversation: create or load (tenant-scoped)      │
│    ├─ 4. Load message history from DB                      │
│    │                                                       │
│    ├─ 5. Orchestrator loop ──────────────────────────────┐ │
│    │      │                                              │ │
│    │      ├─► Anthropic API (claude-sonnet-4-6)          │ │
│    │      │      tool_use blocks ◄──────────────────┐   │ │
│    │      │                                         │   │ │
│    │      └─► Tool dispatcher                       │   │ │
│    │              ├─ Role gate                      │   │ │
│    │              ├─ Pydantic validation             │   │ │
│    │              ├─ Sanitizer (tokenize IDs)        │   │ │
│    │              └─► SQL Server [gold] ─────────────┘   │ │
│    │                                                      │ │
│    │       until end_turn or max_iterations ──────────────┘ │
│    │                                                        │
│    ├─ 6. Persist messages (conversation_message)            │
│    ├─ 7. Persist audit row (ai_audit_log)                   │
│    ├─ 8. Record token usage (rate limiter)                  │
│    └─ 9. Detokenize response text → return ChatResponse     │
└────────────────────────────────────────────────────────────┘
           │                          │
           ▼                          ▼
    SQL Server [gold]          SQL Server [api_audit]
    (analytical views)         (conversations + audit)
```

---

## Roles

| Role | Description | Sanitizer active | Can call `get_audit_trail` |
|---|---|---|---|
| `direccion` | Full access, raw IDs in responses | No | Yes |
| `marca` | Brand-level scope | Yes | No |
| `tienda` | Store-level scope | Yes | No |
| `sku` | SKU-level scope | Yes | No |

For roles other than `direccion`, the sanitizer replaces `sku_id`, `store_id`, and `brand_id` with opaque tokens (`entity_<hex8>`) before sending data to Claude. Tokens are resolved back to display names in the final response.

---

## Roadmap

- **Phase 5.1 ✅** — Three composite weekly briefing tools with parallel sub-calls (`asyncio.gather`), 5s timeouts, and partial-failure isolation; `is_composite` flag in registry; 15 tools total
- **Phase 5.2 ✅** — Four role-specific system prompts (direccion, marca, tienda, sku) with 7 mandatory sections each; `select_prompt(role)` wired into `chat.py`; 169 tests
- **Phase 5.3 ✅** — Bounded 3-turn memory (`MEMORY_TURNS_PER_REQUEST=3`); `load_recent_messages` with tenant isolation; `GET /api/v1/conversations/{id}` summary endpoint; 182 tests
- **Phase 5.4 ✅** — Eval framework: 20-question catalog, EvalRunner with mock-client CI support, metrics (tool_hit_rate, concept_coverage, by_role), RunComparison for regression detection, text/JSON reports, CLI (`python -m app.evaluation.cli`); 204 tests
- **Phase 5.5 ✅** — Synthetic retail data for `tenant_id=9001` (`sql/synthetic/01_tenant_9001_seed.sql`): 3 brands, 5 stores, 200 SKUs, 52 weeks; 4 alert scenarios (OVERSTOCK/UNDERSTOCK/OBSOLETE/STOCK_ZERO); ABCD velocity distribution; idempotente DELETE+INSERT
- **Phase 6 ⏳** — Operational console UI: per-store dashboard, weekly action list, alert drill-down, plan-vs-actual chart
- **Phase 7 ⏳** — Multi-tenant onboarding automation; Redis-backed rate limiter for multi-worker deployments; advanced cost and margin analytics

See [../docs/](../docs/) for architecture, data contract, API reference and runbook.
