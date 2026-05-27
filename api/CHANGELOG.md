# Changelog

All notable changes to the Retail AI Platform API are recorded here.

---

## [Unreleased] — Sub-fase 5.6

- Re-run eval against tenant 9001; save baseline artifact
- Commit + tag `v0.5-prompts-complete`

---

## [5.5.0] — 2026-05-27 — Synthetic retail data (tenant 9001)

### Added

- **`sql/synthetic/01_tenant_9001_seed.sql`** — idempotente DELETE+INSERT para tenant 9001 (RetailDemo SA). Pobla las siete tablas gold necesarias para todas las herramientas de la API:
  - `gold.dim_category` — 3 categorías: Ropa, Calzado, Accesorios
  - `gold.dim_store` — 5 tiendas: 4 retail (T01-T04) + 1 depósito (T05), `store_id` 101-105
  - `gold.dim_sku` — 200 SKUs con `brand_id`, `brand_name`, `list_price` y `category_id` embebidos; generados con CTE recursivo + `CROSS APPLY` (sin tablas ERP)
  - `gold.dim_business_rules` — 4 reglas: genérica + una por marca con distintos umbrales de cobertura y obsolescencia
  - `gold.fact_sales_weekly` — ~52 semanas × patrones store/sku deterministas; usa `CHECKSUM` con cast a `BIGINT` para evitar overflow `ABS(INT_MIN)`; genera distribución ABCD de velocidad
  - `gold.fact_stock_weekly` — últimas 4 semanas × combinaciones sku/store filtradas; 4 escenarios de alerta embebidos
  - `gold.fact_sales_plan` — 156 filas (52 semanas × 3 marcas a nivel agregado store_id=0)
- **`sql/synthetic/README.md`** — documentación del tenant sintético, instrucciones de ejecución, tabla de escenarios de alertas, limitaciones conocidas (tickets=0), uso con eval CLI

### Alert scenarios in vw_active_alerts

| Tipo | SKUs | Severidad |
|---|---|---|
| OVERSTOCK | 1-10 | HIGH / MEDIUM |
| UNDERSTOCK | 11-20 | HIGH |
| OBSOLETE | 141-155 | MEDIUM |
| STOCK_ZERO | 181-190 | HIGH (con velocidad) |
| STOCK_ZERO | 191-200 | MEDIUM (sin velocidad) |

---

## [5.4.0] — 2026-05-27 — Eval framework

### Added

- **`app/evaluation/catalog.py`** — 20 `EvalQuestion` frozen dataclasses (5 per role: direccion, marca, tienda, sku). Each question has `expected_tools` (any-match) and `expected_concepts` (Spanish keywords). Import-time assertions ensure exactly 20 questions with unique IDs.
- **`app/evaluation/runner.py`** — `EvalRunner` runs the catalog against a real or mocked tenant via `run_conversation()`. Produces an `EvalRun` with one `QuestionResult` per question (tool_hit bool, concept_hits list, duration_ms, error capture).
- **`app/evaluation/metrics.py`** — `compute_metrics(run)` returns `EvalMetrics` with `tool_hit_rate`, `concept_coverage` (avg per-question hit rate), `success_rate`, `avg_latency_ms`, `avg_tokens_*`, and a `by_role` breakdown.
- **`app/evaluation/comparator.py`** — `compare_runs(run_a, run_b)` produces a `RunComparison` with `improved` / `regressed` / `unchanged` question lists and a `to_dict()` with deltas for tool_hit_rate, concept_coverage, and latency.
- **`app/evaluation/report.py`** — `render_json(run)` (full JSON artifact) and `render_text(run)` (human-readable table with ✓/✗ per question, global metrics, by-role section).
- **`app/evaluation/cli.py`** — `python -m app.evaluation.cli run --tenant N [--role R] [--ids Q01,Q02] [--output file.json] [--text]` and `python -m app.evaluation.cli compare run_a.json run_b.json [--output diff.json]`.
- **`tests/test_evaluation/test_eval_framework.py`** — 22 deterministic tests using the same `SimpleNamespace + AsyncMock` mock-client pattern as test_orchestrator.py. No real API calls in CI.

### Tests

- 204 passed (up from 182 after Sub-fase 5.3)
- 22 new eval framework tests

---

## [5.3.0] — Bounded conversational memory

### Added

- `MEMORY_TURNS_PER_REQUEST=3` env var in `config.py` (user+assistant pair = 1 turn; configurable for A/B testing)
- `load_recent_messages(conv_id, *, tenant_id, turns=None)` in `conversation.py` — fetches last N pairs in chronological order using TOP + ORDER BY DESC + reverse; tenant isolation via EXISTS subquery
- `count_messages(conv_id)` helper
- `GET /api/v1/conversations/{id}` endpoint — returns `ConversationSummary` with total_messages, total_turns, memory_turns, and last N message snippets; 404 for unknown or foreign-tenant conversations
- `chat.py` switched from `load_messages` to `load_recent_messages`
- `_parse_message_rows(rows)` extracted helper shared by both loaders

### Tests

- 182 passed (up from 169 after Sub-fase 5.2)

---

## [5.2.0] — Role-specific system prompts

### Added

- `app/llm/prompts/direccion.py`, `marca.py`, `tienda.py`, `sku.py` — four role prompts, each with 7 mandatory sections (ROL, HERRAMIENTAS, WORKFLOW, ESTILO, IDIOMA, TÉRMINOS, LÍMITES)
- All prompts enforce español rioplatense with voseo, monolingual Spanish default, and explicit prohibition on invented numbers
- `app/llm/prompts/selector.py` — `select_prompt(role: str | None) -> str` with case-insensitive lookup and `GENERIC_SYSTEM_PROMPT` fallback for unknown roles
- `chat.py` wired to `select_prompt(auth.role)` replacing the hardcoded generic prompt

### Tests

- 169 passed (up from 137 after Sub-fase 5.1)

---

## [5.1.0] — Three composite briefing tools

### Added

- **`get_executive_weekly_briefing`** (direccion) — tenant KPIs + plan + alerts + brands + actions in one round-trip; Phase 1 serial week resolution + Phase 2 parallel sub-calls
- **`get_store_daily_briefing`** (tienda, marca, direccion) — store KPIs + store-scoped alerts + critical SKUs (RED/YELLOW only, max 10)
- **`get_brand_weekly_review`** (marca, direccion) — brand KPIs + brand-scoped alerts + ABCD velocity summary aggregated by segment
- `_gather_safe(*named_coros, timeout)` helper: `asyncio.gather(return_exceptions=True)` + `asyncio.wait_for(5s)` per sub-call; returns `(results, failures)`
- `_composition` and `_partial_failures` fields injected into output dicts after `model_dump()`
- `is_composite: bool = False` flag added to `_entry()` and all composite registry entries
- `fetch_latest_week(tenant_id, *, store_id=None)` in `queries.py`

### Changed

- `TOOL_REGISTRY` grows from 12 to 15 entries

### Tests

- 137 passed (up from ~115 before Sub-fase 5.1)
