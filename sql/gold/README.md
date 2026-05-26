# `sql/gold` — Gold layer

13 numbered SQL scripts that build the `[gold]` schema, populate it from
the source ERP, and expose analytical views.

## Pre-requisites

1. **SQL Server 2019+** (uses `CONCAT_WS`, `HASHBYTES('SHA2_256')`, window
   functions, computed columns).
2. **Target database** — pick one. The scripts deploy `[gold]` *inside* the
   same database as the source ERP `dbo` tables, since the refresh
   procedures `JOIN` across schemas. The reference name used in the scripts
   is `pymeconta_local` — change it (or just run inside your equivalent DB).
3. **Source ERP schema present** — eight tables under `dbo` are read by the
   refresh procs. See [`../../docs/data-contract.md`](../../docs/data-contract.md).
4. **One tenant to test with.** The seeding scripts (`04_*`) target tenant
   id `7` (the POC tenant). For other tenants, copy the seed procs and
   substitute the id, or build an admin UI that writes directly to the
   enrichment tables.

## Run order

Execute scripts **in numeric order** against the target database.

| # | Script | What it does | Idempotent? |
|---|---|---|---|
| 01 | `01_schema_and_logging.sql` | Creates `[gold]` schema + `etl_batch_log` + `etl_data_quality_metrics`. | DROP+CREATE — destroys logs |
| 02 | `02_dim_date.sql` | Calendar dimension + populator. Loads 2020-01-01..2030-12-31. | DROP+CREATE, then `sp_populate` is idempotent per range |
| 03 | `03_enrichment_tables.sql` | 6 manual enrichment tables (brand, season, store class, society, business rules, sales plan) + sentinel rows. | DROP+CREATE |
| 04 | `04_seeding_procs_emp7.sql` | 5 seed procs for the POC tenant. Run after `05_*` for the sales-plan seed. | Each proc is idempotent (DELETE+INSERT per tenant) |
| 05 | `05_dimensions_refresh.sql` | `dim_category`, `dim_store`, `dim_sku` + refresh procs (MERGE + soft-delete). | DROP+CREATE; refresh procs use MERGE |
| 06_1 | `06_1_fact_sales_weekly.sql` | Weekly sales aggregate + refresh proc (DELETE+INSERT per week window). | Refresh proc is idempotent per window |
| 06_2 | `06_2_fact_stock_weekly.sql` | Weekly stock snapshot with forward-fill + dead-pair filter. | Same |
| 06_3 | `06_3_fact_stock_movements.sql` | Kardex fact + incremental refresh (watermark on movement id). | Incremental |
| 06_4 | `06_4_fact_transfers.sql` | Transfers fact + incremental refresh. | Incremental |
| 07 | `07_analytical_views.sql` | 7 views: pipeline, coverage status, ABCD velocity, store/brand dashboards, alerts, action priority. | Pure views; safe to redeploy |
| 08 | `08_master_orchestrator.sql` | `sp_refresh_all(@tenant_id, @batch_id OUTPUT)` — runs the whole pipeline. | Whole pipeline is idempotent |
| 09 | `09_validations.sql` | `sp_run_validations(@tenant_id)` — 18 checks (PK, FK, range, cross-check). | Read-only |
| 10 | `10_e2e_dashboard.sql` | End-to-end script for SSMS: seedings + refresh + validations + 6 dashboard grids. | Re-runnable |

## End-to-end smoke test

Open `10_e2e_dashboard.sql` in SSMS and execute. Expected output:

**Messages tab:**
```
STEP 0: pre-requisitos OK
STEP 1: seedings OK (~20 ms)
STEP 2: sp_refresh_all OK (~700 ms) batch=<guid>
STEP 3: validaciones OK (~60 ms)
STEP 4: dashboard (6 grids)
PIPELINE COMPLETO en ~1000 ms
```

**Results tab — 7 grids:**

1. **Validations (18 rows)** — should be 16 PASS / 2 WARN / 0 FAIL. The two
   WARNs are expected for a B2B distributor profile (over-coverage and
   high-margin services).
2. **4.1 Inventario dimensional** — single-row counts of dims and facts.
3. **4.2 Ventas última semana** — single-row summary (units, revenue,
   COGS, margin).
4. **4.3 Store dashboard** — one row per active store.
5. **4.4 Brand performance** — one row per brand including plan-vs-actual.
6. **4.5 Stock fin semana** — stock totals per store for the latest week.
7. **4.6 Alertas activas** — count by alert type and severity, total
   estimated impact.

**Cross-checks that MUST be exact** (validations 9.6.a, 9.6.b, 9.7):

| Validation | Gold | Direct from source | Diff |
|---|---|---|---|
| 9.6.a SUM(units_sold_net) | should equal | should equal | 0 |
| 9.6.b SUM(revenue_net) | should equal | should equal | 0 |
| 9.7 SUM(stock_units) latest week | should equal | should equal | 0 |

If any cross-check fails, **stop** — there is a data integrity issue
between Gold and the source.

## Adapting for another tenant

1. Copy `sp_seed_*_emp7` to `sp_seed_*_<tenant_alias>` and change the
   hardcoded tenant id and the heuristics (brand by code, store
   classification, rules).
2. Adjust the `IF @tenant_id = 7` guard inside `sp_refresh_all` (block 08)
   so the right seeds run for the right tenant — or remove the guard if
   you decide all tenants should self-seed.
3. Run `EXEC gold.sp_refresh_all @tenant_id = <new id>, @batch_id = NULL OUTPUT;`
4. Run `EXEC gold.sp_run_validations @tenant_id = <new id>;` and confirm
   the cross-checks (9.6, 9.7) are 0.
