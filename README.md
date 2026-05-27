# Retail AI Platform

A multi-tenant analytical platform that turns transactional ERP data into
weekly retail decisions (replenish / transfer / liquidate / re-price) backed
by AI-assisted recommendations.

## Estado del proyecto

| Fase | Estado | Descripción |
|---|---|---|
| Fase 3 — Gold warehouse | ✅ Completo | 13 SQL scripts: dims, facts, 7 analytical views, orchestrator, 18-check validation suite. Cross-checks pass to the cent. |
| Fase 4 — REST API | ✅ Completo | FastAPI + 10 Claude tools, JWT auth, sanitizer, rate limiter, audit trail. 88 tests passing. |
| Fase 5 — AI agent layer | 🚧 En curso | Per-role system prompts; triage, brand-analyst, store-analyst and what-if agents. |
| Fase 6 — UI | ⏳ Planificado | Operational console: per-store dashboard, weekly action list, alert drill-down, plan-vs-actual. |
| Fase 7 — Scale & automation | ⏳ Planificado | Multi-tenant onboarding automation, Redis-backed rate limiter, advanced cost analytics. |

## Architecture (3-minute version)

**Source layer** — a multi-tenant SQL Server ERP (invoicing, inventory,
accounting, fiscal integration). Eight core tables drive the pipeline:
documents, document lines, products, categories, warehouses, the
warehouse-product index, the kardex (stock movements) and a per-tenant
currency lookup. The ERP is consumed read-only; nothing is written back.

**Gold layer** — a `[gold]` schema in SQL Server that materialises five
star-schema facts (`fact_sales_weekly`, `fact_stock_weekly`,
`fact_stock_movements`, `fact_transfers`, `fact_sales_plan`) over four
dimensions (`dim_date`, `dim_sku`, `dim_store`, `dim_category`) plus six
manual enrichment tables (brand, season, store classification, society,
business rules, sales plan) that capture retail concepts absent from the
generic ERP. Every fact is rebuilt idempotently per tenant by a single
master procedure that logs each step to `etl_batch_log` and persists DQ
indicators to `etl_data_quality_metrics`.

**Analytics layer** — seven views (`vw_sku_coverage_status`,
`vw_sku_velocity_segmented`, `vw_store_dashboard`, `vw_brand_performance`,
`vw_active_alerts`, `vw_action_recommendation_priority`,
`vw_sales_pipeline`) expose the operational questions: which SKUs are
stockout-risk, which are obsolete, which are over-stocked, which actions
have the highest dollar impact today. These are the data contracts the
upcoming API and AI agents will consume.

## Repository layout

```
retail-ai-platform/
├── README.md                  -- this file
├── CHANGELOG.md               -- version history (keepachangelog format)
├── LICENSE                    -- MIT
├── .gitignore
├── sql/
│   └── gold/                  -- 13 SQL scripts (run in order) + README
├── docs/
│   ├── architecture.md        -- Bronze/Silver/Gold layering + AI tool pattern
│   ├── data-contract.md       -- per-tool API reference (10 tools, inputs/outputs, Gold views)
│   ├── api-reference.md       -- HTTP endpoint reference (POST /chat, GET /health, error codes)
│   ├── runbook.md             -- deploy, refresh, add tenant, rotate secrets, investigate
│   └── discovery/             -- Phases 1-3 reports (ERP reverse engineering)
└── api/                       -- FastAPI service (Phase 4, complete)
    ├── README.md              -- quick start, env table, curl examples, CLI, architecture
    └── app/                   -- source code
```

## What's next

**Phase 5 — AI agent layer 🚧.** Per-role system prompts. Wire specialised agents on top of the
10 tools: a triage agent that surfaces the day's top actions, a brand
analyst, a store analyst, and a what-if simulator for pricing and
transfers.

**Phase 6 — UI ⏳.** A focused operational console: per-store dashboard,
weekly action list, alert drill-down, plan-vs-actual.

**Phase 7 — Scale & automation ⏳.** Multi-tenant onboarding automation, Redis-backed rate limiter for multi-worker deployments, advanced cost and margin analytics.

## Requirements

- SQL Server 2019 or newer (the Gold layer uses `CONCAT_WS`, `HASHBYTES`
  SHA2_256, computed columns, window functions).
- A target database where the `[gold]` schema lives.
- Read access to the source ERP tables enumerated in
  [docs/data-contract.md](docs/data-contract.md).

The reference database name throughout the SQL scripts is `pymeconta_local`,
which is **the local development database used by the author**. Each deployer
should adapt the `USE <database>;` statements (only block 10 carries one) and
ensure the source ERP tables live in the same database under `dbo`.

## Quick start

See [sql/gold/README.md](sql/gold/README.md) for the exact run order and
[docs/runbook.md](docs/runbook.md) for the full deployment recipe.
