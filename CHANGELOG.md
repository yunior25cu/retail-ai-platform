# Changelog

All notable changes are documented here following [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

Versions correspond to sub-phases of the project roadmap (Phase 3 = Gold warehouse, Phase 4 = API).

---

## [Unreleased]

---

## [0.4.6] — 2026-05-26

### Added
- `api/README.md` — full rewrite: quick start, env table, curl examples (health, mock auth, JWT, marca role), CLI examples, test commands, ASCII architecture diagram, roles table, roadmap
- `docs/data-contract.md` — rewritten as per-tool API reference for all 10 tools with input/output tables, Gold views consumed, CLI examples, and example JSON
- `docs/api-reference.md` — new HTTP endpoint reference: `POST /api/v1/chat`, `GET /api/v1/health`, all error codes with example JSON bodies, request headers
- `docs/runbook.md` — extended with API operation procedures: deploy, rotate JWT secret, investigate via audit log, adjust rate limits, add a tenant to the API
- `CHANGELOG.md` — this file (keepachangelog format)
- OpenAPI improvements in `app/main.py`, `app/api/v1/chat.py`, `app/api/v1/health.py`: descriptions, tags, response schema examples

---

## [0.4.5] — 2026-05-25

### Added
- JWT authentication (`HS256`, `python-jose`): `create_access_token` / `decode_access_token` in `app/auth/jwt_handler.py`
- Auth dependency `get_auth_context`: resolves identity from Bearer JWT → mock `X-Mock-*` headers → dev defaults; `AUTH_REQUIRE_JWT=true` disables the mock path
- In-memory sliding-window rate limiter (`app/security/rate_limiter.py`): per-tenant 100/h, per-user 30/h, per-tenant 1M tokens/day; configurable via env
- Audit persister (`app/audit/persister.py`): writes to `api_audit.ai_audit_log`; `estimate_cost_usd` using claude-sonnet-4-6 pricing ($3/$15 per MTok input/output); `hash_text` SHA-256
- HTTP 429 response at `POST /api/v1/chat` with `{"detail": {"scope": "tenant|user|tokens", "message": "..."}}`
- 88 tests across `test_health`, `test_tools/*`, `test_llm/*`, `test_chat_endpoint`, `test_security/*`, `test_audit/*`

---

## [0.4.4] — 2026-05-23

### Added
- 7 additional Gold tools completing the 10-tool registry:
  - `get_executive_summary` — composite tool: tenant totals + plan + distinct tickets + top-3 alerts in one LLM round-trip
  - `get_sku_detail` — master fields + last-8-weeks sales + current stock per store + active alerts for a single SKU
  - `get_sku_coverage_status` — per-SKU traffic-light (RED/YELLOW/GREEN/GREY) with days-of-coverage and suggested action
  - `get_velocity_segmentation` — ABCD velocity segmentation over last 8 weeks
  - `get_action_recommendations` — top-N actions ranked by severity × estimated dollar impact
  - `compare_periods` — compare one metric across two ISO weeks by tenant, brand or store; dynamic SQL with enum-validated allowlist (SQL-injection-safe)
  - `get_audit_trail` — audit row by request_id; restricted to `direccion` role
- `python -m app.tools.cli` — CLI runner for all 10 tools with Pydantic validation and role gating

### Fixed
- `SkuStoreStock.last_sale_date` changed from `str | None` to `date | None` to match pyodbc return type; `model_dump(mode="json")` serialises to ISO string

---

## [0.4.3] — 2026-05-21

### Added
- Multi-turn conversation persistence: `api_audit.conversation` + `api_audit.conversation_message`; messages stored as JSON Anthropic content blocks
- `app/db/conversation.py`: `create_conversation`, `load_conversation`, `touch_conversation`, `append_message`, `load_messages`
- Bi-directional sanitizer (`app/security/sanitizer.py`): for roles ≠ `direccion`, replaces `sku_id`/`store_id`/`brand_id` with opaque tokens (`entity_<hex8>`) before sending to Claude; `detokenize_text` resolves tokens back to display names in the final response
- Token map persisted to `api_audit.conversation_token_map`; same token returned for same entity in the same conversation
- `POST /api/v1/chat` wired end-to-end: rate limit → resolve/create conversation → load history → orchestrator with sanitizer → persist messages → persist audit → record tokens → detokenize → `ChatResponse`
- `app/db/conversation.py`: `insert_token_map`, `find_token_map`, `load_token_map`, `fetch_display_names` (batched per entity type)

---

## [0.4.2] — 2026-05-19

### Added
- Anthropic SDK integration (`AsyncAnthropic`, `claude-sonnet-4-6`): `app/llm/claude_client.py` with placeholder-key guard
- Tool-calling loop: `app/llm/orchestrator.py`; iterates `tool_use` blocks up to `max_iterations`; returns `ConversationResult(request_id, response_text, iterations, stop_reason, tokens_input, tokens_output, tools_invoked)`
- Role-based tool filtering: `anthropic_tools(role)` in `app/tools/__init__.py` hides tools the caller's role cannot invoke; LLM never sees restricted definitions
- Tool dispatcher (`app/llm/tool_dispatcher.py`): role gate → Pydantic validation → async tool execution → error normalisation
- Generic system prompt in `app/llm/prompts/generic.py`

---

## [0.4.1] — 2026-05-16

### Added
- FastAPI project scaffold with `pydantic-settings` (`app/config.py`) — all settings env-driven with `.env` file support
- Structured logging via `structlog` (JSON or console renderer; configurable via `LOG_JSON` / `LOG_LEVEL`)
- `pyodbc` connection pool with `asyncio.to_thread` adapter (`app/db/connection.py`); pool size configurable
- `GET /api/v1/health` with real SQL Server readiness probe (tenant count, database name)
- `api_audit` schema: 4 tables — `conversation`, `conversation_message`, `conversation_token_map`, `ai_audit_log`
- First 3 Gold tools: `get_active_alerts`, `get_store_dashboard`, `get_brand_performance` with Pydantic input models and Anthropic tool definitions

### Fixed
- `ISNULL(?, MAX(...))` pyodbc null-binding issue in `fetch_tenant_weekly_totals` split into two round-trips: first resolve the latest week, then aggregate — avoids type-inference truncation

---

## [0.3.0] — 2026-05-10

### Added
- Gold data warehouse (13 SQL scripts under `sql/gold/`):
  - `01` — `[gold]` schema + `etl_batch_log` + `etl_data_quality_metrics`
  - `02` — `dim_date` calendar (2020–2030), `sp_populate_dim_date`, `iso_year_week CHAR(8)` format `YYYY-Www`
  - `03` — 6 manual enrichment tables: `dim_brand_mapping`, `dim_season_mapping`, `dim_store_classification`, `dim_society_mapping`, `dim_business_rules`, `fact_sales_plan`
  - `04` — Seed stored procedures for the POC tenant (brand heuristic, store classification, business rules, society, plan = historical × 1.10)
  - `05` — `dim_category`, `dim_store`, `dim_sku` with `sp_refresh_*` (MERGE + SHA2-256 change detection + soft-delete)
  - `06_1` — `fact_sales_weekly`: weekly sales aggregate, `estado IN (1,2)`, COGS from kardex, semi-additive ticket count
  - `06_2` — `fact_stock_weekly`: forward-fill snapshot with `OUTER APPLY`, dead-pair filter (84 days at zero)
  - `06_3` — `fact_stock_movements`: incremental by kardex watermark
  - `06_4` — `fact_transfers`: inter-store (vale_salida with `destino=4`), incremental
  - `07` — 7 analytical views: `vw_active_alerts`, `vw_action_recommendation_priority`, `vw_store_dashboard`, `vw_brand_performance`, `vw_sku_coverage_status`, `vw_sku_velocity_segmented`, `vw_sales_pipeline`
  - `08` — `sp_refresh_all` master orchestrator + 6 DQ metrics persisted to `etl_data_quality_metrics`
  - `09` — `sp_run_validations` with 18 checks (PK, FK, range, enrichment, 3 cross-checks)
  - `10` — end-to-end SSMS script with RAISERROR progress + 7 result grids

### Fixed
- `rule` (T-SQL reserved keyword) renamed to `obs_rule` as OUTER APPLY alias in `06_2_fact_stock_weekly.sql`
- `vw_store_dashboard.tickets` filter aligned from `estado=2` to `IN (1,2)` (was showing 0 tickets while revenue was non-zero)
- `vw_active_alerts` OVERSTOCK `suggested_action` corrected to `LIQUIDAR` for PRO BRAND (was incorrectly showing `REPONER`)
- `sp_seed_sales_plan_emp7` filter aligned to `estado IN (1,2)` (was missing W19 draft invoices)
- `producto.codigo` deduplication in brand seed via `ROW_NUMBER()` (source ERP allows duplicate codes per tenant)
- `SELECT 1` in existence subqueries given alias `AS one` (SQL Server requires column aliases in subqueries)
