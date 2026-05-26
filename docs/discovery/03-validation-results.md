# Phase 3 — Validation results

End-to-end smoke test for the POC tenant after running the full
pipeline (`sp_refresh_all` → `sp_run_validations` → 6 dashboard grids).

## Timing

| Stage | Time |
|---|---|
| Seedings (4 procs) | ~19 ms |
| `sp_refresh_all` (master) | ~700 ms |
| `sp_run_validations` (18 checks) | ~80 ms |
| Dashboard grids (6 SELECTs) | ~30 ms |
| **End-to-end SQL time** | **~940 ms** |

## Validations summary

**18 checks executed — 16 PASS / 2 WARN / 0 FAIL.**

| Category | Count | Notes |
|---|---|---|
| PK uniqueness (4 facts) | 4 PASS | SQL Server enforces — sanity checks |
| FK orphans (6 fact→dim joins) | 6 PASS | Including `fact_stock_movements → dim_sku` (the only `WARN` severity check; still PASS in practice) |
| Range checks (3) | 1 PASS + 2 WARN | margin% out of range and coverage > 365 days both fire for B2B distributor profile |
| Enrichment coverage (2) | 2 PASS | All POC SKUs got a brand, all stores got a classification |
| Cross-checks vs source (3) | 3 PASS | EXACT to the cent — see below |

## Cross-checks (the hard gates)

These three checks compare Gold aggregates against direct queries on
the source ERP with the same filters. If any of these fail, the
snapshot is invalid.

| Check | Gold | Direct from source | Diff |
|---|---|---|---|
| 9.6.a `SUM(units_sold_net)` | 30,091 | 30,091 | **0** |
| 9.6.b `SUM(revenue_net)` (base currency) | 2,557,341.29 | 2,557,341.29 | **0.00** |
| 9.7 `SUM(stock_units)` latest week | 37,739 | 37,739 | **0** |

All three exact.

## Data-quality metrics persisted to `etl_data_quality_metrics`

7 indicators captured by the master refresh:

| Metric | Value | Severity | Comment |
|---|---|---|---|
| `gold.dim_sku.duplicate_sku_codes` | 1 | WARN | Source ERP allows duplicate codes; dedupe handled in brand seeding |
| `gold.dim_sku.skus_without_brand` | 0 | INFO | Seeding covered all 100 active SKUs |
| `gold.dim_store.stores_without_classification` | 0 | INFO | All 4 warehouses classified |
| `gold.fact_sales_weekly.sales_with_negative_margin_pct` | 10 | WARN | Below-cost sales / service lines with COGS=0 inflating absolute negative margin |
| `gold.vw_sku_coverage_status.skus_with_coverage_over_365_days` | 14 | WARN | Heavy over-stock typical of B2B distribution |
| `gold.fact_sales_weekly.facts_with_missing_dim_join` | 0 | INFO | Zero referential leakage from fact to dim |
| `gold.fact_stock_weekly.rows_with_negative_stock` | 1 | WARN | Source kardex has one row with negative `saldo` (legitimate timing artefact in the ERP) |

## Inventory of materialised data

| Object | Rows (POC tenant) |
|---|---|
| `gold.dim_sku` (active) | 100 |
| `gold.dim_store` (active) | 4 |
| `gold.dim_category` | 9 |
| `gold.fact_sales_weekly` | 692 |
| `gold.fact_stock_weekly` | 2,370 |
| `gold.fact_stock_movements` | 1,620 |
| `gold.fact_transfers` | 13 |
| `gold.fact_sales_plan` | 75 |
| `gold.vw_active_alerts` | 46 |

## Bugs caught during the build (and fixed)

| # | Symptom | Cause | Fix |
|---|---|---|---|
| 1 | Parse error on `OUTER APPLY` alias `rule` | `rule` is a T-SQL reserved-ish keyword (`CREATE RULE`) | Renamed to `obs_rule` in `06_2` |
| 2 | `SUM(tickets)` over-counts | `tickets = COUNT(DISTINCT doc_id)` per PK bucket → semi-additive | Documented; dashboards re-derive with `COUNT(DISTINCT)` against source |
| 3 | `vw_store_dashboard.tickets` showed 0 while `revenue > 0` | Tickets sub-query filtered `estado = 2`, fact filtered `IN (1,2)` | Aligned tickets filter to `IN (1,2)` |
| 4 | OVERSTOCK alerts suggested `REPONER` | Rule action propagated mechanically; brand rule said REPONER | Hardcoded `LIQUIDAR` for overstock |
| 5 | `sp_seed_sales_plan_emp7` missed week W19 | Filtered `estado = 2` only; W19 sales were drafts | Aligned to `IN (1,2)` |
| 6 | `SELECT 1` without alias rejected by SQL Server | Subquery in `EXISTS`-style requires column name | Aliased to `SELECT 1 AS one` |
| 7 | Duplicate `producto.codigo` broke PK on `dim_brand_mapping` | Source allows duplicate codes per tenant | Dedupe in brand seed: `ROW_NUMBER OVER (PARTITION BY codigo ORDER BY updated_at DESC)` |

All fixes are committed into the corresponding script files.

## What this validates

- The data contract with the source ERP is correctly understood and
  consistently applied.
- The Gold aggregates match the source to the cent for both sales and
  stock.
- The pipeline is idempotent (running it twice produces the same
  snapshot — verified by re-running and observing `inserted` and
  `deleted` counts in `etl_batch_log`).
- Multi-tenant isolation works (every refresh proc scopes by
  `@tenant_id`; no cross-tenant leakage).
- The end-to-end script is fast enough to run interactively for the POC
  tenant and produces a complete operational dashboard in one SSMS
  session.

## What this does NOT validate

- Production-scale performance (10k+ SKUs, 50+ stores, multi-year).
  Some `OUTER APPLY` patterns in `fact_stock_weekly` will need
  optimisation at that scale.
- Multi-currency aggregation. The POC tenant has a single base currency
  and `tasa_cambio = 1` throughout. Currency conversion logic is
  present but untested under non-trivial FX.
- Real retail business rules. The POC business rules
  (`dim_business_rules` seed) are synthetic and tuned to a B2B
  distributor. A real retailer would replace them.
