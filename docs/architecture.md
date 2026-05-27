# Architecture

## Layering

The platform follows a Bronze / Silver / Gold separation, with one twist:
the Silver layer is implicit (it lives inside the source ERP's own
materialised views and stored procedures, which already compute cost,
balance and current stock). We consume those directly when we can and
only re-derive what the ERP does not expose cleanly.

```
┌─────────────────────────────────────────────────────────────────────┐
│ Bronze — source ERP (read-only)                                     │
│   • Transactional tables: documents, lines, payments, kardex movs   │
│   • Master tables: products, warehouses, categories, currencies     │
│   • Source SP: SP_U_SUBMAYOR_INVENTARIO (PMP cost roll-forward)     │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │ read-only joins
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Silver — (implicit, inside the source ERP)                          │
│   • kardex rows already carry running balance, unit cost, value     │
│   • document headers carry resolved totals in base currency         │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │ MERGE + aggregation
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Gold — analytical model (this repository)                           │
│                                                                     │
│   Dimensions (refreshed per-tenant via MERGE):                      │
│     dim_date     dim_sku     dim_store     dim_category             │
│                                                                     │
│   Enrichment dims (MANUAL — absent from ERP):                       │
│     dim_brand_mapping        dim_season_mapping                     │
│     dim_store_classification dim_society_mapping                    │
│     dim_business_rules                                              │
│                                                                     │
│   Facts:                                                            │
│     fact_sales_weekly        fact_stock_weekly  (forward-filled)    │
│     fact_stock_movements     fact_transfers     fact_sales_plan     │
│                                                                     │
│   Analytical views (weekly):                                        │
│     vw_sku_coverage_status   vw_sku_velocity_segmented              │
│     vw_store_dashboard       vw_brand_performance                   │
│     vw_active_alerts         vw_action_recommendation_priority      │
│     vw_sales_pipeline                                               │
│                                                                     │
│   Analytical views (monthly — sub-phase 4.7):                       │
│     vw_sales_monthly         vw_stock_monthly_eom                   │
│     vw_brand_performance_monthly  vw_store_dashboard_monthly        │
│                                                                     │
│   Cross-cutting:                                                    │
│     etl_batch_log   etl_data_quality_metrics                        │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │ tenant-scoped SELECT
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│ API — Phase 4 ✅ + Phase 5 ✅                                        │
│   15 tools (function-calling) + role-based system prompts           │
│   POST /api/v1/chat  ·  GET /api/v1/health                          │
│   GET /api/v1/conversations/{id}                                    │
│   JWT auth · rate limiter · sanitizer · audit log                   │
│   Bounded conversational memory (MEMORY_TURNS_PER_REQUEST=3)        │
└──────────────────────────────────┬──────────────────────────────────┘
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Eval framework — Phase 5.4 ✅                                        │
│   20-question catalog (5/rol) · EvalRunner · metrics · comparator   │
│   python -m app.evaluation.cli run/compare                          │
│   Synthetic tenant 9001 (sql/synthetic/) — Phase 5.5 ✅             │
└─────────────────────────────────────────────────────────────────────┘
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│ UI (Phase 6, planned)                                               │
└─────────────────────────────────────────────────────────────────────┘
```

## Key design decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | `[gold]` lives **inside the source database** | Avoids cross-DB joins, keeps the master refresh atomic-ish, fastest path for a POC. Production may split this. |
| 2 | Multi-tenant via `tenant_id` column on **every** Gold table | Single physical model; row-level isolation enforced by every refresh proc filtering `WHERE id_empresa = @tenant_id`. |
| 3 | Manual enrichment for retail concepts the ERP lacks (brand, season, store class, society) | The source ERP is a generic invoicing/inventory platform; retail-specific dimensions are not in the data model. We add them as overlay tables that the dim refresh procs consume. |
| 4 | `documento_producto.devuelto` is the canonical source of returns | The ERP also stores returns as separate documents (`tipo_documento=4`). Using both would double-count. We pick the line-level field. |
| 5 | Costs come from the kardex (`submayor_inventario.costo`), not from `producto.costo` | The ERP recomputes weighted average cost per movement via stored procedure. `producto.costo` is often stale or zero. |
| 6 | Forward-fill in `fact_stock_weekly`, with dead-pair filter (>12 weeks at zero) | Snapshot semantics require every alive SKU×store to have a value every week, even when no movement occurred. Dead pairs would bloat the table linearly. |
| 7 | `tickets` in `fact_sales_weekly` is **semi-additive** | Computed as `COUNT(DISTINCT doc_id)` *per PK bucket*. Re-aggregations must use `COUNT(DISTINCT)` directly against the source, not `SUM` of this column. Dashboards do this correctly. |
| 8 | Every refresh logs to `etl_batch_log` with a shared `batch_id` | Lets us correlate sub-steps, time-box each one, and surface failures. DQ metrics for the same batch land in `etl_data_quality_metrics`. |
| 9 | Cross-checks 9.6/9.7 are hard gates | `units_sold_net`, `revenue_net` and `stock_units` MUST match the source to the cent for a refresh to be considered valid. |

## The Phase 4 AI tool pattern

The Gold views are already shaped as **operational questions**, not raw
data. Each view answers one question that an LLM agent (or a human
operator) routinely asks:

| View | Question it answers |
|---|---|
| `vw_sku_coverage_status` | For every SKU×store, is the stock too thin, just right, too deep, or obsolete — and what's the suggested action? |
| `vw_sku_velocity_segmented` | Which SKUs are fast / medium / slow / dead movers (ABCD)? |
| `vw_store_dashboard` | This week, per store: sales, margin, tickets, stock health. |
| `vw_brand_performance` | This week, per brand: sales vs plan, margin, stock. |
| `vw_active_alerts` | What alerts (stockout / obsolete / over / under) are firing right now, sorted by dollar impact? |
| `vw_action_recommendation_priority` | Top-N actions to take this week, weighted by severity and impact. |
| `vw_sales_pipeline` | Open / draft sales not yet confirmed. |

For Phase 4 these become **function-calling tools** with JSON schemas:
each tool gets a tenant id (resolved from the auth token), optionally a
filter (brand, store, severity, top-N), and returns the rows as
structured JSON. The agent then composes them — e.g., "show me the top 5
overstock alerts for brand X this week and propose a transfer to a store
where the same SKU is under-stocked" maps to:
`vw_active_alerts(filter=overstock,brand=X,top=5)` →
`vw_sku_coverage_status(brand=X,status=UNDERSTOCK)` →
recommend transfers.

The Gold layer's role is to make sure those tools always return numbers
that match the operational reality — which is exactly what the
cross-checks enforce.

## ISO week-to-month assignment (sub-phase 4.7)

The monthly layer assigns every ISO week entirely to the month containing
its **Thursday** (ISO 8601 rule). This is implemented via two persisted
computed columns added to `gold.dim_date`:

```sql
year_month_iso  CHAR(7)  -- '2026-01', computed from DATEADD(day, 4-day_of_week, [date])
month_id_iso    INT      -- 202601, for fast sort/join
```

**Implication**: a week that straddles a month boundary (e.g., Mon 29-Dec –
Sun 4-Jan) is assigned in full to the month of its Thursday. This means
the Gold monthly totals will **not** coincide exactly with the ERP's
accounting-period totals in months that contain such cross-boundary weeks.
The expected discrepancy is < 5% in normal months and < 2% in months where
only a few days cross over. See
[docs/temporal-aggregation-notes.md](temporal-aggregation-notes.md) for
quantification and the Level 2 (physical `fact_sales_monthly`) upgrade path.
