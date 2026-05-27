# Data contract — API tools

This document is the Phase 4 reference for the ten function-calling tools exposed by `POST /api/v1/chat`. For each tool it lists: required inputs, output fields, which Gold views or tables it queries, a CLI invocation, and an abbreviated example JSON response.

For the Phase 3 source ERP tables that feed the Gold layer (the eight `dbo.*` tables), see [discovery/01-erp-discovery.md](discovery/01-erp-discovery.md) and [architecture.md](architecture.md).

---

## Table of contents

1. [get_active_alerts](#1-get_active_alerts)
2. [get_store_dashboard](#2-get_store_dashboard)
3. [get_brand_performance](#3-get_brand_performance)
4. [get_executive_summary](#4-get_executive_summary)
5. [get_sku_detail](#5-get_sku_detail)
6. [get_sku_coverage_status](#6-get_sku_coverage_status)
7. [get_velocity_segmentation](#7-get_velocity_segmentation)
8. [get_action_recommendations](#8-get_action_recommendations)
9. [compare_periods](#9-compare_periods)
10. [get_audit_trail](#10-get_audit_trail)
11. [Tablas Gold consumidas](#tablas-gold-consumidas)

---

## 1. `get_active_alerts`

List currently active operational alerts (stockout, obsolete, overstock, understock) ordered by estimated dollar impact descending.

### Inputs

| Parameter | Type | Default | Description |
|---|---|---|---|
| `level` | `string \| null` | `null` | Filter by alert level: `SKU` / `STORE` / `BRAND` / `EXECUTIVE` |
| `severity` | `string \| null` | `null` | Filter by severity: `HIGH` / `MEDIUM` / `LOW` |
| `limit` | `integer` | `20` | Maximum rows to return. Range: 1–200. |

### Outputs (one object per alert)

| Field | Type | Description |
|---|---|---|
| `alert_id` | `string` | Synthetic key (`<alert_type>_<store_id>_<sku_id>_<week>`) |
| `iso_year_week` | `string` | Week the alert was computed, format `YYYY-Www` |
| `level` | `string` | `SKU` / `STORE` / `BRAND` / `EXECUTIVE` |
| `alert_type` | `string` | `STOCKOUT` / `OBSOLETE` / `OVERSTOCK` / `UNDERSTOCK` |
| `severity` | `string` | `HIGH` / `MEDIUM` / `LOW` |
| `store_id` | `integer \| null` | Store dimension key |
| `sku_id` | `integer \| null` | SKU dimension key |
| `brand_id` | `integer \| null` | Brand dimension key |
| `metric_value` | `float \| null` | Observed value triggering the alert |
| `threshold` | `float \| null` | Threshold value crossed |
| `suggested_action` | `string \| null` | `REPONER` / `LIQUIDAR` / `TRANSFERIR` / `REVISAR` |
| `estimated_impact_usd` | `float \| null` | Dollar impact estimate |

### Gold views consumed

`gold.vw_active_alerts`

### CLI example

```bash
python -m app.tools.cli get_active_alerts --tenant 7 --severity HIGH --limit 5 --pretty
```

### Example JSON

```json
[
  {
    "alert_id": "STOCKOUT_7_44_2026-W22",
    "iso_year_week": "2026-W22",
    "level": "SKU",
    "alert_type": "STOCKOUT",
    "severity": "HIGH",
    "store_id": 7,
    "sku_id": 44,
    "brand_id": 1,
    "metric_value": 0.0,
    "threshold": 5.0,
    "suggested_action": "REPONER",
    "estimated_impact_usd": 2340.50
  }
]
```

---

## 2. `get_store_dashboard`

Per-store KPIs for the latest reported week: units sold, revenue, gross margin, ticket count, stock units and value, plus counts of zero-stock and obsolete SKUs.

### Inputs

| Parameter | Type | Default | Description |
|---|---|---|---|
| `store_id` | `integer \| null` | `null` | Return only this store. Omit for all active stores. |
| `week_id` | `string \| null` | `null` | ISO week `YYYY-Www` (e.g. `2026-W22`). Only the latest reported week is currently supported. |

### Outputs (one object per store)

| Field | Type | Description |
|---|---|---|
| `iso_year_week` | `string` | Reporting week |
| `store_id` | `integer` | Store dimension key |
| `store_code` | `string` | ERP warehouse code |
| `store_name` | `string` | Store display name |
| `block_AB` | `string` | `A` (retail) / `B` (depot) classification |
| `is_store_flag` | `boolean` | `true` for retail stores, `false` for depots |
| `units_sold` | `float` | Net units sold (returns deducted) |
| `revenue` | `float` | Net revenue in base currency |
| `cogs` | `float` | Cost of goods sold |
| `gross_margin` | `float` | Revenue − COGS |
| `gross_margin_pct` | `float \| null` | Gross margin / revenue |
| `tickets` | `integer` | Distinct sales transactions (COUNT DISTINCT from source) |
| `avg_ticket` | `float \| null` | Revenue / tickets |
| `stock_units` | `float` | Current stock units (latest snapshot) |
| `stock_value` | `float` | Current stock value |
| `skus_in_store` | `integer` | Active SKU count in this store |
| `skus_zero_stock` | `integer` | SKUs with zero stock |
| `skus_obsolete` | `integer` | SKUs flagged as obsolete |

### Gold views consumed

`gold.vw_store_dashboard`

### CLI example

```bash
python -m app.tools.cli get_store_dashboard --tenant 7 --pretty
python -m app.tools.cli get_store_dashboard --tenant 7 --store-id 7 --pretty
```

### Example JSON

```json
[
  {
    "iso_year_week": "2026-W22",
    "store_id": 7,
    "store_code": "ALM001",
    "store_name": "Sucursal Centro",
    "block_AB": "A",
    "is_store_flag": true,
    "units_sold": 482.0,
    "revenue": 238400.00,
    "cogs": 142100.00,
    "gross_margin": 96300.00,
    "gross_margin_pct": 0.4040,
    "tickets": 459,
    "avg_ticket": 519.39,
    "stock_units": 3210.0,
    "stock_value": 1920000.00,
    "skus_in_store": 87,
    "skus_zero_stock": 4,
    "skus_obsolete": 2
  }
]
```

---

## 3. `get_brand_performance`

Per-brand KPIs for the latest reported week: units sold, revenue, gross margin, plan-vs-actual ratios, stock, and SKU health counts.

### Inputs

| Parameter | Type | Default | Description |
|---|---|---|---|
| `brand_id` | `integer \| null` | `null` | Return only this brand. Omit for all brands. |
| `week_id` | `string \| null` | `null` | ISO week `YYYY-Www`. Only the latest reported week is currently supported. |

### Outputs (one object per brand)

| Field | Type | Description |
|---|---|---|
| `iso_year_week` | `string` | Reporting week |
| `brand_id` | `integer` | Brand dimension key |
| `brand_name` | `string` | Brand display name |
| `units_sold` | `float` | Net units sold |
| `revenue` | `float` | Net revenue |
| `cogs` | `float` | Cost of goods sold |
| `gross_margin` | `float` | Revenue − COGS |
| `gross_margin_pct` | `float \| null` | Gross margin / revenue |
| `planned_units` | `float` | Units from sales plan |
| `planned_revenue` | `float` | Revenue from sales plan |
| `units_vs_plan_pct` | `float \| null` | `units_sold / planned_units` |
| `revenue_vs_plan_pct` | `float \| null` | `revenue / planned_revenue` |
| `stock_units` | `float` | Stock across all stores |
| `stock_value` | `float` | Stock value across all stores |
| `skus_count` | `integer` | Active SKU count for this brand |
| `skus_zero_stock` | `integer` | SKUs with zero stock |
| `skus_obsolete` | `integer` | Obsolete SKUs |

### Gold views consumed

`gold.vw_brand_performance`

### CLI example

```bash
python -m app.tools.cli get_brand_performance --tenant 7 --pretty
python -m app.tools.cli get_brand_performance --tenant 7 --brand-id 1 --pretty
```

### Example JSON

```json
[
  {
    "iso_year_week": "2026-W22",
    "brand_id": 1,
    "brand_name": "PRO BRAND",
    "units_sold": 210.0,
    "revenue": 105000.00,
    "cogs": 63000.00,
    "gross_margin": 42000.00,
    "gross_margin_pct": 0.40,
    "planned_units": 240.0,
    "planned_revenue": 120000.00,
    "units_vs_plan_pct": 0.875,
    "revenue_vs_plan_pct": 0.875,
    "stock_units": 1500.0,
    "stock_value": 900000.00,
    "skus_count": 32,
    "skus_zero_stock": 2,
    "skus_obsolete": 1
  }
]
```

---

## 4. `get_executive_summary`

Director-level snapshot in a single tool call: tenant-wide totals, plan-vs-actual, real distinct ticket count, and the top 3 alerts by dollar impact. Saves ~5K input tokens compared to chaining `get_store_dashboard` + `get_brand_performance` + `get_active_alerts`.

### Inputs

| Parameter | Type | Default | Description |
|---|---|---|---|
| `week_id` | `string \| null` | `null` | ISO week `YYYY-Www`. Defaults to the latest reported week. |

### Outputs (single object)

| Field | Type | Description |
|---|---|---|
| `week_id` | `string` | Resolved ISO week |
| `units_sold` | `float` | Tenant-wide net units sold |
| `revenue` | `float` | Tenant-wide net revenue |
| `cogs` | `float` | Tenant-wide COGS |
| `gross_margin` | `float` | Tenant-wide gross margin |
| `gross_margin_pct` | `float \| null` | Gross margin / revenue |
| `tickets` | `integer` | Distinct sales transactions (re-derived from source, not semi-additive) |
| `avg_ticket` | `float \| null` | Revenue / tickets |
| `planned_units` | `float \| null` | Plan total for this week |
| `planned_revenue` | `float \| null` | Plan revenue for this week |
| `units_vs_plan_pct` | `float \| null` | `units_sold / planned_units` |
| `revenue_vs_plan_pct` | `float \| null` | `revenue / planned_revenue` |
| `top_alerts` | `array` | Top 3 alerts by estimated dollar impact |

Each `top_alerts` item:

| Field | Type | Description |
|---|---|---|
| `alert_id` | `string` | Alert identifier |
| `level` | `string` | `SKU` / `STORE` / `BRAND` / `EXECUTIVE` |
| `alert_type` | `string` | `STOCKOUT` / `OBSOLETE` / `OVERSTOCK` / `UNDERSTOCK` |
| `severity` | `string` | `HIGH` / `MEDIUM` / `LOW` |
| `store_id` | `integer \| null` | — |
| `sku_id` | `integer \| null` | — |
| `brand_id` | `integer \| null` | — |
| `suggested_action` | `string \| null` | — |
| `estimated_impact_usd` | `float \| null` | — |

### Gold views / tables consumed

`gold.fact_sales_weekly`, `gold.fact_sales_plan`, `gold.vw_active_alerts`, plus a direct COUNT DISTINCT from `dbo.documento` for real ticket count.

### CLI example

```bash
python -m app.tools.cli get_executive_summary --tenant 7 --pretty
python -m app.tools.cli get_executive_summary --tenant 7 --week-id 2026-W19 --pretty
```

### Example JSON

```json
{
  "week_id": "2026-W22",
  "units_sold": 1240.0,
  "revenue": 620000.00,
  "cogs": 372000.00,
  "gross_margin": 248000.00,
  "gross_margin_pct": 0.40,
  "tickets": 1183,
  "avg_ticket": 524.09,
  "planned_units": 1400.0,
  "planned_revenue": 700000.00,
  "units_vs_plan_pct": 0.886,
  "revenue_vs_plan_pct": 0.886,
  "top_alerts": [
    {
      "alert_id": "STOCKOUT_7_44_2026-W22",
      "level": "SKU",
      "alert_type": "STOCKOUT",
      "severity": "HIGH",
      "store_id": 7,
      "sku_id": 44,
      "brand_id": 1,
      "suggested_action": "REPONER",
      "estimated_impact_usd": 2340.50
    }
  ]
}
```

---

## 5. `get_sku_detail`

Full SKU profile: master fields, last 8 weeks of sales, current stock per store, and active alerts. Use when a specific SKU is named.

### Inputs

| Parameter | Type | Default | Description |
|---|---|---|---|
| `sku_id` | `integer` | _(required)_ | Internal SKU id from `dim_sku`. |
| `store_id` | `integer \| null` | `null` | Scope sales and stock to one store. Omit for all stores. |

### Outputs (single object or `null` if SKU not found)

| Field | Type | Description |
|---|---|---|
| `master` | `object` | All `dim_sku` fields for this SKU (code, name, brand, category, list price, etc.) |
| `sales_last_8w` | `array` | One object per week, last 8 weeks |
| `stock_by_store` | `array` | One object per store, current snapshot |
| `active_alerts` | `array` | Alerts where `sku_id` matches |

`sales_last_8w` item fields:

| Field | Type |
|---|---|
| `iso_year_week` | `string` |
| `units_sold` | `float` |
| `revenue` | `float` |
| `gross_margin` | `float` |
| `tickets_semiadd` | `integer` |

`stock_by_store` item fields:

| Field | Type |
|---|---|
| `iso_year_week` | `string` |
| `store_id` | `integer` |
| `stock_units` | `float` |
| `stock_value` | `float` |
| `unit_cost` | `float` |
| `has_zero_stock_flag` | `boolean` |
| `is_obsolete_flag` | `boolean` |
| `days_since_last_sale` | `integer \| null` |
| `days_since_last_movement` | `integer \| null` |
| `last_sale_date` | `string \| null` (ISO date) |
| `last_movement_date` | `string \| null` (ISO date) |

### Gold views / tables consumed

`gold.dim_sku`, `gold.fact_sales_weekly`, `gold.fact_stock_weekly`, `gold.vw_active_alerts`

### CLI example

```bash
python -m app.tools.cli get_sku_detail --tenant 7 --sku-id 7 --pretty
python -m app.tools.cli get_sku_detail --tenant 7 --sku-id 7 --store-id 7 --pretty
```

---

## 6. `get_sku_coverage_status`

Per-SKU coverage status with a traffic-light colour (RED / YELLOW / GREEN / GREY): current stock, days of coverage, target band from business rules, and suggested action. Filterable by brand, store, status colour, or single SKU.

### Inputs

| Parameter | Type | Default | Description |
|---|---|---|---|
| `brand_id` | `integer \| null` | `null` | Filter by brand |
| `store_id` | `integer \| null` | `null` | Filter by store |
| `status` | `string \| null` | `null` | `RED` / `YELLOW` / `GREEN` / `GREY` |
| `sku_id` | `integer \| null` | `null` | Single-SKU filter |
| `limit` | `integer` | `50` | Maximum rows. Range: 1–500. |

### Outputs (one object per SKU×store)

| Field | Type | Description |
|---|---|---|
| `iso_year_week` | `string` | Reporting week |
| `store_id` | `integer` | — |
| `sku_id` | `integer` | — |
| `sku_code` | `string` | — |
| `sku_name` | `string` | — |
| `brand_id` | `integer` | — |
| `brand_name` | `string` | — |
| `category_id` | `integer \| null` | — |
| `stock_units` | `float` | Current stock |
| `stock_value` | `float` | Stock value |
| `unit_cost` | `float` | Weighted-average unit cost |
| `has_zero_stock_flag` | `boolean` | `true` if stock = 0 |
| `is_obsolete_flag` | `boolean` | `true` if no movement for >90 days |
| `days_since_last_sale` | `integer \| null` | — |
| `units_per_day_4w` | `float` | Average daily velocity (last 4 weeks) |
| `days_coverage` | `float \| null` | `stock_units / units_per_day_4w` |
| `target_min_days` | `integer` | Minimum coverage from business rules |
| `target_max_days` | `integer` | Maximum coverage from business rules |
| `suggested_action` | `string` | `REPONER` / `LIQUIDAR` / `TRANSFERIR` / `OK` |
| `suggested_discount_pct` | `float \| null` | Suggested liquidation discount |
| `status_color` | `string` | `RED` / `YELLOW` / `GREEN` / `GREY` |

### Gold views consumed

`gold.vw_sku_coverage_status`

### CLI example

```bash
python -m app.tools.cli get_sku_coverage_status --tenant 7 --status RED --limit 5 --pretty
python -m app.tools.cli get_sku_coverage_status --tenant 7 --brand-id 1 --pretty
```

---

## 7. `get_velocity_segmentation`

ABCD segmentation of active SKUs by units sold over the last 8 weeks. A = top 25% by volume, B = next 25%, C = next 25%, D = slowest 25% (zeros included).

### Inputs

| Parameter | Type | Default | Description |
|---|---|---|---|
| `segment` | `string \| null` | `null` | Filter by letter: `A` / `B` / `C` / `D` |
| `brand_id` | `integer \| null` | `null` | Filter by brand |
| `limit` | `integer` | `100` | Maximum rows. Range: 1–500. |

### Outputs (one object per SKU)

| Field | Type | Description |
|---|---|---|
| `sku_id` | `integer` | — |
| `sku_code` | `string` | — |
| `sku_name` | `string` | — |
| `brand_id` | `integer` | — |
| `brand_name` | `string` | — |
| `category_id` | `integer \| null` | — |
| `units_8w` | `float` | Total units sold in last 8 weeks |
| `revenue_8w` | `float` | Total revenue in last 8 weeks |
| `weeks_with_sales` | `integer` | Weeks with at least one unit sold |
| `units_per_day_avg` | `float` | Average daily velocity |
| `velocity_segment` | `string` | `A` / `B` / `C` / `D` |

### Gold views consumed

`gold.vw_sku_velocity_segmented`

### CLI example

```bash
python -m app.tools.cli get_velocity_segmentation --tenant 7 --segment A --pretty
python -m app.tools.cli get_velocity_segmentation --tenant 7 --brand-id 1 --limit 20 --pretty
```

---

## 8. `get_action_recommendations`

Top-N recommended actions ranked by priority (severity × estimated dollar impact). Filterable by alert level (scope) and severity.

### Inputs

| Parameter | Type | Default | Description |
|---|---|---|---|
| `scope` | `string \| null` | `null` | Alert level: `SKU` / `STORE` / `BRAND` / `EXECUTIVE` |
| `severity` | `string \| null` | `null` | `HIGH` / `MEDIUM` / `LOW` |
| `limit` | `integer` | `10` | Maximum rows. Range: 1–100. |

### Outputs (one object per recommendation)

| Field | Type | Description |
|---|---|---|
| `priority_rank` | `integer` | 1 = highest priority |
| `alert_id` | `string` | Alert identifier |
| `iso_year_week` | `string` | Week |
| `level` | `string` | Alert level |
| `alert_type` | `string` | Alert type |
| `severity` | `string` | Severity |
| `store_id` | `integer \| null` | — |
| `sku_id` | `integer \| null` | — |
| `brand_id` | `integer \| null` | — |
| `metric_value` | `float \| null` | — |
| `threshold` | `float \| null` | — |
| `suggested_action` | `string \| null` | — |
| `estimated_impact_usd` | `float \| null` | — |
| `priority_score` | `float \| null` | Composite priority score |

### Gold views consumed

`gold.vw_action_recommendation_priority`

### CLI example

```bash
python -m app.tools.cli get_action_recommendations --tenant 7 --limit 5 --pretty
python -m app.tools.cli get_action_recommendations --tenant 7 --scope SKU --severity HIGH --pretty
```

---

## 9. `compare_periods`

Compare one sales metric across two ISO weeks, broken down by tenant (single row), brand, or store. Returns absolute and percent delta.

### Inputs

| Parameter | Type | Default | Description |
|---|---|---|---|
| `metric` | `string` | _(required)_ | One of: `units_sold_net`, `units_sold_gross`, `revenue_net`, `revenue_gross`, `gross_margin`, `cogs`, `tickets`, `discount_amount` |
| `period_a` | `string` | _(required)_ | Base period, format `YYYY-Www` |
| `period_b` | `string` | _(required)_ | Comparison period, format `YYYY-Www` |
| `scope` | `string` | `tenant` | Breakdown: `tenant` / `brand` / `store` |

Both metric and scope are validated against a fixed allowlist; dynamic SQL injection is not possible.

### Outputs (one object per scope bucket)

| Field | Type | Description |
|---|---|---|
| `scope_id` | `integer \| null` | Brand or store id; `null` for tenant scope |
| `scope_label` | `string \| null` | Display name; `TOTAL` for tenant scope |
| `value_a` | `float` | Metric value for `period_a` |
| `value_b` | `float` | Metric value for `period_b` |
| `delta_abs` | `float` | `value_b − value_a` |
| `delta_pct` | `float \| null` | `(value_b − value_a) / value_a`; `null` if `value_a == 0` |

### Gold views / tables consumed

`gold.fact_sales_weekly` (direct SELECT with dynamic metric column, enum-validated)

### CLI example

```bash
python -m app.tools.cli compare_periods --tenant 7 \
  --metric revenue_net --period-a 2026-W18 --period-b 2026-W19 --scope brand --pretty
```

### Example JSON

```json
[
  {
    "scope_id": 1,
    "scope_label": "PRO BRAND",
    "value_a": 98000.00,
    "value_b": 105000.00,
    "delta_abs": 7000.00,
    "delta_pct": 0.0714
  }
]
```

---

## 10. `get_audit_trail`

Retrieve the full audit row for a previous `/chat` request: user question, tools invoked with their inputs, token usage, cost in USD, and the final response. **Restricted to the `direccion` role.**

### Inputs

| Parameter | Type | Default | Description |
|---|---|---|---|
| `request_id` | `string` | _(required)_ | UUID from a prior `ChatResponse.request_id`. Length: 8–64 characters. |

### Outputs (single object or `null` if not found for this tenant)

| Field | Type | Description |
|---|---|---|
| `request_id` | `string` | UUID of the original request |
| `conversation_id` | `string \| null` | Conversation that contained this request |
| `user_id` | `string` | Caller user ID |
| `user_role` | `string` | Caller role |
| `timestamp_utc` | `string` | ISO timestamp of the request |
| `user_question` | `string \| null` | Original user message |
| `tools_invoked` | `array \| null` | Each tool call: name, input, duration_ms, is_error |
| `final_response` | `string \| null` | Claude's answer (before detokenization) |
| `tokens_input` | `integer \| null` | Input tokens consumed |
| `tokens_output` | `integer \| null` | Output tokens generated |
| `cost_usd` | `float \| null` | Estimated cost (claude-sonnet-4-6 pricing) |
| `duration_ms` | `integer \| null` | Total request duration |
| `status` | `string` | `SUCCESS` / `PARTIAL` / `ERROR` |
| `error_msg` | `string \| null` | Error detail for `ERROR` status |

### Tables consumed

`api_audit.ai_audit_log` (tenant-scoped)

### CLI example

```bash
python -m app.tools.cli get_audit_trail --tenant 7 --role direccion \
  --request-id 3fa85f64-5717-4562-b3fc-2c963f66afa6 --pretty
```

---

## Tablas Gold consumidas

The following Gold objects are queried by the tools above. All are in the `gold` schema of the configured `SQL_DATABASE`.

| Object | Type | Consumed by |
|---|---|---|
| `vw_active_alerts` | View | `get_active_alerts`, `get_executive_summary`, `get_sku_detail` |
| `vw_store_dashboard` | View | `get_store_dashboard` |
| `vw_brand_performance` | View | `get_brand_performance` |
| `vw_sku_coverage_status` | View | `get_sku_coverage_status` |
| `vw_sku_velocity_segmented` | View | `get_velocity_segmentation` |
| `vw_action_recommendation_priority` | View | `get_action_recommendations` |
| `fact_sales_weekly` | Fact table | `get_executive_summary`, `compare_periods`, `get_sku_detail` |
| `fact_stock_weekly` | Fact table | `get_sku_detail` (stock by store) |
| `fact_sales_plan` | Fact table | `get_executive_summary` (plan totals) |
| `dim_sku` | Dimension | `get_sku_detail` (master fields) |
| `dim_store` | Dimension | Detokenizer (display names) |
| `dim_brand_mapping` | Enrichment | Detokenizer (brand display names) |

The audit tool reads from `api_audit.ai_audit_log`, which is outside the Gold schema and stores operational metadata rather than analytical data.

Every query includes `WHERE tenant_id = @tenant_id` as the first filter condition, enforcing row-level tenant isolation. The `tenant_id` is always resolved from the JWT claims — it is never accepted from the request body.
