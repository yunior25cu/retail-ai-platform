# Temporal Aggregation Notes

## How ISO weeks are assigned to months

The Gold layer uses **ISO 8601 week assignment**: each ISO week is assigned
entirely to the calendar month that contains its **Thursday**.

### Why Thursday?

ISO 8601 defines week 1 of a year as the week containing the year's first
Thursday. By extension, any week belongs to the month whose Thursday falls
within it. This makes the monthly boundaries consistent with the ISO week
numbering already used throughout the Gold layer (`iso_year_week` column).

### Implementation in `gold.dim_date`

Two persisted computed columns (added in `sql/gold/11_monthly_views.sql`):

```sql
year_month_iso AS CONVERT(CHAR(7),
    DATEADD(day, 4 - day_of_week, [date]), 120) PERSISTED  -- '2026-01'

month_id_iso AS (
    YEAR (DATEADD(day, 4 - day_of_week, [date])) * 100
  + MONTH(DATEADD(day, 4 - day_of_week, [date]))) PERSISTED  -- 202601
```

`day_of_week` is already stored (1=Mon…7=Sun, ISO-consistent). Adding
`4 - day_of_week` always lands on the Thursday of the same ISO week.

### Edge-case verification

| Date | day_of_week | Thursday of week | year_month_iso |
|---|---|---|---|
| 2026-01-01 (Thu) | 4 | 2026-01-01 | `2026-01` |
| 2025-12-29 (Mon) | 1 | 2026-01-01 | `2026-01` ← assigned to January |
| 2025-12-28 (Sun) | 7 | 2025-12-25 | `2025-12` ← stays in December |
| 2026-03-30 (Mon) | 1 | 2026-04-02 | `2026-04` ← assigned to April |

---

## The cross-month boundary problem

Weeks that straddle a month boundary (e.g., Monday 29 Dec through Sunday
4 Jan) are assigned **entirely** to one month. This creates an inherent
mismatch between:

- **Gold monthly totals** — all sales in the week go to the month of the Thursday
- **ERP accounting totals** — each day's sales appear in the actual calendar month

### Typical discrepancy magnitude

| Scenario | Discrepancy |
|---|---|
| Month with no cross-boundary weeks | ~0% |
| Month with one cross-boundary week (normal) | < 2% of monthly revenue |
| Month with two cross-boundary weeks (rare) | < 5% of monthly revenue |

Cross-boundary weeks occur when the 1st or last days of a month fall on
Mon/Tue/Wed (start of a week whose Thursday is still in the other month)
or Thu/Fri/Sat/Sun (end of a week whose Thursday was in the previous
month).

### When does this matter?

**Doesn't matter (operational use):**
- Week-over-week trend analysis — Gold weekly figures are exact
- Month-over-month relative comparisons within the Gold system
- AI recommendations (stockout / overstock / transfer) — based on weekly facts

**Matters (accounting reconciliation):**
- Comparing Gold monthly totals with the ERP's fiscal accounting reports
- Comparing with VAT/tax filings (which use calendar days, not ISO weeks)
- Any audit that reconciles to the ERP's own period totals

### Workaround for reconciliation

If a client requires exact calendar-month matching with the ERP:

1. **Short-term**: export daily-grain data from `fact_sales_weekly` (join
   back through `dbo.documento` and `dbo.documento_producto`) and re-group
   by calendar month.
2. **Level 2 upgrade**: create a physical `fact_sales_monthly` table built
   from daily sales transactions keyed on `YEAR(fecha_emision)` and
   `MONTH(fecha_emision)`. This provides exact calendar-month totals at the
   cost of an additional ETL step and table. Estimated scope: 2–3 days.
   This is outside the Phase 4.7 Level 1 scope and should be quoted
   separately.

---

## vw_stock_monthly_eom — EOM snapshot logic

The stock monthly view uses the **last day of the calendar month**
(EOMONTH) as the snapshot date — not the last Friday/Sunday of the ISO
week. This is derived directly from `dbo.submayor_inventario`:

```
For each (tenant, month, store, sku):
  → OUTER APPLY TOP 1 WHERE fecha_emision <= MAX(dim_date.[date] WHERE year_month_iso = M)
  → ORDER BY fecha_emision DESC, si.id DESC
```

For the current (incomplete) month, the EOM date is today's date (the
last date present in `dim_date` for the current month), so the view shows
the most recent stock snapshot available, not a future projection.

---

## Summary table — periodicity support

| Granularity | Supported | Source | Exact vs ERP |
|---|---|---|---|
| ISO week (`YYYY-Www`) | Yes | `fact_sales_weekly` | Exact |
| Calendar month (`YYYY-MM`) | Yes (Level 1) | `vw_sales_monthly` (derived) | ~98-100% match |
| Calendar quarter | No | — | — |
| Calendar year | No | — | — |
| Calendar month (exact) | Level 2 (not built) | `fact_sales_monthly` (physical) | Exact |
