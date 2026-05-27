SET QUOTED_IDENTIFIER ON;
SET ANSI_NULLS ON;
GO

/* ============================================================
 * 11_monthly_views.sql
 * Purpose : Monthly periodicity layer (Level 1 — derived views, no physical
 *           monthly facts). Adds two computed columns to dim_date for ISO-based
 *           month assignment, then creates four analytical views.
 *
 * ISO month assignment rule (ISO 8601):
 *   A week belongs to the month that contains its Thursday.
 *   Weeks straddling a month boundary are assigned entirely to the month of
 *   their Thursday. See docs/temporal-aggregation-notes.md for implications.
 *
 * Depends  : 02_dim_date.sql, 06_1_fact_sales_weekly.sql,
 *            06_2_fact_stock_weekly.sql, 03_enrichment_tables.sql (dim_store,
 *            dim_sku), 07_analytical_views.sql (pattern only — no runtime dep)
 * Idempotent: yes — IF NOT EXISTS guards on ALTER TABLE + CREATE OR ALTER VIEW
 * ============================================================ */


/* ============================================================
 * PART 1 — dim_date: add year_month_iso and month_id_iso
 * ============================================================
 *
 * Formula:
 *   Thursday of the ISO week = DATEADD(day, 4 - day_of_week, [date])
 *     day_of_week=1 (Mon): +3 → Thu
 *     day_of_week=4 (Thu): +0 → same
 *     day_of_week=7 (Sun): -3 → Thu
 *
 *   year_month_iso = CONVERT(CHAR(7), thursday_date, 120)  → 'YYYY-MM'
 *   month_id_iso   = YYYY * 100 + MM                       → integer for fast sort/join
 *
 * All functions used (DATEADD, CONVERT, YEAR, MONTH) are deterministic
 * → columns can be PERSISTED.
 *
 * Verification of edge cases:
 *   2026-01-01 (Thu, dow=4): Thu = same → '2026-01'  ✓
 *   2025-12-29 (Mon, dow=1): Thu = 2026-01-01 → '2026-01'  (cross-month, assigned to Jan) ✓
 *   2025-12-28 (Sun, dow=7): Thu = 2025-12-25 → '2025-12'  ✓
 * ============================================================ */

IF COL_LENGTH('gold.dim_date', 'year_month_iso') IS NULL
    ALTER TABLE gold.dim_date ADD
        year_month_iso AS CONVERT(CHAR(7),
            DATEADD(day, 4 - day_of_week, [date]), 120) PERSISTED;
GO
IF COL_LENGTH('gold.dim_date', 'month_id_iso') IS NULL
    ALTER TABLE gold.dim_date ADD
        month_id_iso AS (
            YEAR (DATEADD(day, 4 - day_of_week, [date])) * 100
          + MONTH(DATEADD(day, 4 - day_of_week, [date]))) PERSISTED;
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = 'ix_dim_date_month_iso'
      AND object_id = OBJECT_ID('gold.dim_date')
)
    CREATE INDEX ix_dim_date_month_iso ON gold.dim_date (year_month_iso);
GO


/* ============================================================
 * PART 2 — vw_sales_monthly
 *
 * Granularity : 1 row per (tenant_id, year_month_iso, store_id, sku_id,
 *               brand_id, category_id) — same grain as fact_sales_weekly but
 *               collapsed across all ISO weeks assigned to the same month.
 *
 * Join key    : dim_date.day_of_week = 4 (Thursday) — one Thursday per ISO
 *               week → guarantees a 1:1 join from fact to calendar month.
 *
 * tickets     : SUM across weeks. Semi-additive if the same sales document
 *               spans multiple week-assignments (rare but possible at month
 *               boundaries). Use COUNT(DISTINCT) via dbo.documento for
 *               exact monthly ticket counts (see vw_store_dashboard_monthly).
 *
 * gross_margin_pct : recalculated at monthly grain from SUM(margin) /
 *               SUM(revenue_net). Do NOT average the weekly pct values.
 * ============================================================ */

CREATE OR ALTER VIEW gold.vw_sales_monthly AS
SELECT
    f.tenant_id,
    dd.year_month_iso,
    dd.month_id_iso,
    f.store_id,
    f.sku_id,
    f.brand_id,
    f.category_id,
    MAX(f.currency_code)                                               AS currency_code,
    CAST(SUM(f.units_sold_gross)  AS DECIMAL(18,4))                   AS units_sold_gross,
    CAST(SUM(f.units_returned)    AS DECIMAL(18,4))                   AS units_returned,
    CAST(SUM(f.units_sold_net)    AS DECIMAL(18,4))                   AS units_sold_net,
    CAST(SUM(f.revenue_gross)     AS DECIMAL(18,4))                   AS revenue_gross,
    CAST(SUM(f.revenue_returned)  AS DECIMAL(18,4))                   AS revenue_returned,
    CAST(SUM(f.revenue_net)       AS DECIMAL(18,4))                   AS revenue_net,
    CAST(SUM(f.cogs)              AS DECIMAL(18,4))                   AS cogs,
    CAST(SUM(f.gross_margin)      AS DECIMAL(18,4))                   AS gross_margin,
    CASE WHEN SUM(f.revenue_net) > 0
         THEN CAST(SUM(f.gross_margin) / SUM(f.revenue_net) AS DECIMAL(9,4))
         ELSE NULL END                                                AS gross_margin_pct,
    SUM(f.tickets)                                                    AS tickets,
    CAST(SUM(f.discount_amount)   AS DECIMAL(18,4))                   AS discount_amount
FROM gold.fact_sales_weekly f
JOIN gold.dim_date dd
    ON dd.iso_year_week = f.iso_year_week
   AND dd.day_of_week   = 4          -- one Thursday per ISO week → correct month
GROUP BY
    f.tenant_id, dd.year_month_iso, dd.month_id_iso,
    f.store_id, f.sku_id, f.brand_id, f.category_id;
GO


/* ============================================================
 * PART 3 — vw_stock_monthly_eom
 *
 * Granularity : 1 row per (tenant_id, year_month_iso, store_id, sku_id)
 *               = end-of-month stock snapshot (EOMONTH of each month).
 *
 * Source      : dbo.submayor_inventario — NOT derived from fact_stock_weekly
 *               (which snaps at week_end_date/Sunday, not calendar month-end).
 *
 * Month set   : derived from fact_sales_weekly date range per tenant (months
 *               that have sales). Stock-only months without any sales are
 *               outside this set.
 *
 * EOM date    : MAX([date]) GROUP BY year_month_iso — last calendar date in
 *               dim_date for that month (= EOMONTH since dim_date runs
 *               through 2030-12-31 with full months).
 *
 * Alive-pairs : from dbo.almacen_producto joined via gold.dim_store for
 *               tenant mapping (avoids full scan of submayor_inventario).
 *               dead_threshold = 84 days (saldo=0 AND no movement in 84d).
 *
 * Performance : OUTER APPLY is evaluated per (alive_pair × month). For a
 *               typical tenant with ~500 pairs × 24 months = 12 000 lookups,
 *               each hitting the indexed submayor_inventario. Acceptable for
 *               a view; materialise to a table (Level 2) if latency is a
 *               concern.
 * ============================================================ */

CREATE OR ALTER VIEW gold.vw_stock_monthly_eom AS
WITH tenant_store_map AS (
    SELECT DISTINCT tenant_id, store_id
    FROM gold.dim_store
),
tenant_months AS (
    SELECT DISTINCT f.tenant_id, dd.year_month_iso, dd.month_id_iso
    FROM gold.fact_sales_weekly f
    JOIN gold.dim_date dd
        ON dd.iso_year_week = f.iso_year_week AND dd.day_of_week = 4
),
eom_dates AS (
    SELECT year_month_iso, month_id_iso, MAX([date]) AS eom_date
    FROM gold.dim_date
    GROUP BY year_month_iso, month_id_iso
),
alive_pairs AS (
    SELECT
        tsm.tenant_id,
        ap.id_almacen          AS store_id,
        ap.id_producto         AS sku_id,
        ap.id                  AS id_almacen_producto,
        ap.min_stock,
        ap.max_stock
    FROM dbo.almacen_producto ap
    JOIN tenant_store_map tsm ON tsm.store_id = ap.id_almacen
)
SELECT
    ap.tenant_id,
    tm.year_month_iso,
    tm.month_id_iso,
    ed.eom_date,
    ap.store_id,
    ap.sku_id,
    CAST(sm.saldo        AS DECIMAL(18,4))   AS stock_units,
    CAST(sm.costo_final  AS DECIMAL(18,4))   AS stock_value,
    CASE WHEN sm.saldo <> 0
         THEN CAST(sm.costo_final / sm.saldo AS DECIMAL(18,4))
         ELSE NULL END                        AS unit_cost,
    CAST(ap.min_stock AS DECIMAL(18,4))      AS stock_min,
    CAST(ap.max_stock AS DECIMAL(18,4))      AS stock_max,
    CAST(CASE WHEN sm.saldo = 0 THEN 1 ELSE 0 END AS BIT) AS has_zero_stock_flag,
    CAST(CASE WHEN DATEDIFF(day, sm.mov_date, ed.eom_date) > 84
              THEN 1 ELSE 0 END AS BIT)       AS is_obsolete_flag
FROM alive_pairs ap
JOIN tenant_months tm ON tm.tenant_id = ap.tenant_id
JOIN eom_dates    ed  ON ed.year_month_iso = tm.year_month_iso
OUTER APPLY (
    SELECT TOP 1
        si.saldo,
        si.costo,
        si.costo_final,
        d.fecha_emision AS mov_date
    FROM dbo.submayor_inventario si
    JOIN dbo.documento d ON d.id = si.id_documento
    WHERE si.id_almacen_producto = ap.id_almacen_producto
      AND d.id_empresa            = ap.tenant_id
      AND d.estado                IN (1, 2)
      AND d.[delete]              = 0
      AND d.fecha_emision         <= ed.eom_date
    ORDER BY d.fecha_emision DESC, si.id DESC
) sm
WHERE sm.saldo IS NOT NULL
  AND NOT (sm.saldo = 0 AND DATEDIFF(day, sm.mov_date, ed.eom_date) > 84);
GO


/* ============================================================
 * PART 4 — vw_brand_performance_monthly
 *
 * Granularity : 1 row per (tenant_id, year_month_iso, brand_id)
 * Months      : all months present in vw_sales_monthly per tenant.
 * Stock       : from vw_stock_monthly_eom (same month) — LEFT JOIN so brands
 *               with sales but no EOM stock record still appear.
 * Plan        : monthly aggregation of fact_sales_plan (weekly plan →
 *               year_month_iso via dim_date.day_of_week=4).
 * ============================================================ */

CREATE OR ALTER VIEW gold.vw_brand_performance_monthly AS
WITH brands AS (
    SELECT DISTINCT tenant_id, brand_id, brand_name
    FROM gold.dim_sku
    WHERE is_active = 1
),
all_months AS (
    SELECT DISTINCT tenant_id, year_month_iso, month_id_iso
    FROM gold.vw_sales_monthly
),
sales_by_brand AS (
    SELECT
        tenant_id, year_month_iso, month_id_iso, brand_id,
        SUM(units_sold_net)  AS units_sold,
        SUM(revenue_net)     AS revenue,
        SUM(cogs)            AS cogs,
        SUM(gross_margin)    AS gross_margin
    FROM gold.vw_sales_monthly
    GROUP BY tenant_id, year_month_iso, month_id_iso, brand_id
),
plan_by_brand AS (
    SELECT
        p.tenant_id,
        dd.year_month_iso,
        p.brand_id,
        SUM(p.planned_units)   AS planned_units,
        SUM(p.planned_revenue) AS planned_revenue
    FROM gold.fact_sales_plan p
    JOIN gold.dim_date dd
        ON dd.iso_year_week = p.iso_year_week AND dd.day_of_week = 4
    GROUP BY p.tenant_id, dd.year_month_iso, p.brand_id
),
stock_by_brand AS (
    SELECT
        s.tenant_id, s.year_month_iso, ds.brand_id,
        SUM(s.stock_units)                       AS stock_units,
        SUM(s.stock_value)                       AS stock_value,
        SUM(CAST(s.has_zero_stock_flag AS INT))  AS skus_zero_stock,
        SUM(CAST(s.is_obsolete_flag    AS INT))  AS skus_obsolete,
        COUNT(*)                                 AS skus_count
    FROM gold.vw_stock_monthly_eom s
    JOIN gold.dim_sku ds ON ds.tenant_id = s.tenant_id AND ds.sku_id = s.sku_id
    GROUP BY s.tenant_id, s.year_month_iso, ds.brand_id
)
SELECT
    b.tenant_id,
    am.year_month_iso,
    am.month_id_iso,
    b.brand_id,
    b.brand_name,
    CAST(ISNULL(sb.units_sold,  0) AS DECIMAL(18,4)) AS units_sold,
    CAST(ISNULL(sb.revenue,     0) AS DECIMAL(18,4)) AS revenue,
    CAST(ISNULL(sb.cogs,        0) AS DECIMAL(18,4)) AS cogs,
    CAST(ISNULL(sb.gross_margin,0) AS DECIMAL(18,4)) AS gross_margin,
    CASE WHEN ISNULL(sb.revenue, 0) > 0
         THEN CAST(ISNULL(sb.gross_margin, 0) / sb.revenue AS DECIMAL(9,4))
         ELSE NULL END                                AS gross_margin_pct,
    CAST(ISNULL(pb.planned_units,   0) AS DECIMAL(18,4)) AS planned_units,
    CAST(ISNULL(pb.planned_revenue, 0) AS DECIMAL(18,4)) AS planned_revenue,
    CASE WHEN ISNULL(pb.planned_units, 0) > 0
         THEN CAST(ISNULL(sb.units_sold, 0) / pb.planned_units AS DECIMAL(9,4))
         ELSE NULL END                                AS units_vs_plan_pct,
    CASE WHEN ISNULL(pb.planned_revenue, 0) > 0
         THEN CAST(ISNULL(sb.revenue, 0) / pb.planned_revenue AS DECIMAL(9,4))
         ELSE NULL END                                AS revenue_vs_plan_pct,
    CAST(ISNULL(stk.stock_units, 0) AS DECIMAL(18,4)) AS stock_units,
    CAST(ISNULL(stk.stock_value, 0) AS DECIMAL(18,4)) AS stock_value,
    ISNULL(stk.skus_count,       0)                   AS skus_count,
    ISNULL(stk.skus_zero_stock,  0)                   AS skus_zero_stock,
    ISNULL(stk.skus_obsolete,    0)                   AS skus_obsolete
FROM brands b
JOIN all_months am ON am.tenant_id = b.tenant_id
LEFT JOIN sales_by_brand sb
    ON sb.tenant_id = b.tenant_id AND sb.brand_id = b.brand_id
   AND sb.year_month_iso = am.year_month_iso
LEFT JOIN plan_by_brand pb
    ON pb.tenant_id = b.tenant_id AND pb.brand_id = b.brand_id
   AND pb.year_month_iso = am.year_month_iso
LEFT JOIN stock_by_brand stk
    ON stk.tenant_id = b.tenant_id AND stk.brand_id = b.brand_id
   AND stk.year_month_iso = am.year_month_iso;
GO


/* ============================================================
 * PART 5 — vw_store_dashboard_monthly
 *
 * Granularity : 1 row per (tenant_id, year_month_iso, store_id)
 * Months      : all months in vw_sales_monthly per tenant.
 * Tickets     : COUNT(DISTINCT dbo.documento.id) — avoids the semi-additivity
 *               of fact_sales_weekly.tickets (a ticket may cross week boundary
 *               but should be counted once per month). Same reason as
 *               vw_store_dashboard (see comment in 7.4).
 * Stock       : vw_stock_monthly_eom (EOM snapshot per store, all SKUs summed).
 * ============================================================ */

CREATE OR ALTER VIEW gold.vw_store_dashboard_monthly AS
WITH all_months AS (
    SELECT DISTINCT tenant_id, year_month_iso, month_id_iso
    FROM gold.vw_sales_monthly
),
sales_by_store AS (
    SELECT
        tenant_id, year_month_iso, month_id_iso, store_id,
        SUM(units_sold_net)  AS units_sold,
        SUM(revenue_net)     AS revenue,
        SUM(cogs)            AS cogs,
        SUM(gross_margin)    AS gross_margin,
        SUM(discount_amount) AS discount_amount
    FROM gold.vw_sales_monthly
    GROUP BY tenant_id, year_month_iso, month_id_iso, store_id
),
tickets_by_store AS (
    /* COUNT(DISTINCT factura) per month — avoids semi-additivity of weekly tickets */
    SELECT
        d.id_empresa    AS tenant_id,
        dd.year_month_iso,
        d.id_almacen    AS store_id,
        COUNT(DISTINCT d.id) AS tickets
    FROM dbo.documento d
    JOIN gold.dim_date dd ON dd.[date] = d.fecha_emision
    WHERE d.tipo_documento = 3
      AND d.estado         IN (1, 2)
      AND d.[delete]       = 0
    GROUP BY d.id_empresa, dd.year_month_iso, d.id_almacen
),
stock_by_store AS (
    SELECT
        tenant_id, year_month_iso,
        store_id,
        SUM(stock_units)                       AS stock_units,
        SUM(stock_value)                       AS stock_value,
        SUM(CAST(has_zero_stock_flag AS INT))  AS skus_zero_stock,
        SUM(CAST(is_obsolete_flag    AS INT))  AS skus_obsolete,
        COUNT(*)                               AS skus_in_store
    FROM gold.vw_stock_monthly_eom
    GROUP BY tenant_id, year_month_iso, store_id
)
SELECT
    ds.tenant_id,
    am.year_month_iso,
    am.month_id_iso,
    ds.store_id,
    ds.store_code,
    ds.store_name,
    ds.block_AB,
    ds.is_store_flag,
    CAST(ISNULL(sl.units_sold,    0) AS DECIMAL(18,4)) AS units_sold,
    CAST(ISNULL(sl.revenue,       0) AS DECIMAL(18,4)) AS revenue,
    CAST(ISNULL(sl.cogs,          0) AS DECIMAL(18,4)) AS cogs,
    CAST(ISNULL(sl.gross_margin,  0) AS DECIMAL(18,4)) AS gross_margin,
    CAST(ISNULL(sl.discount_amount,0) AS DECIMAL(18,4)) AS discount_amount,
    CASE WHEN ISNULL(sl.revenue, 0) > 0
         THEN CAST(ISNULL(sl.gross_margin, 0) / sl.revenue AS DECIMAL(9,4))
         ELSE NULL END                                  AS gross_margin_pct,
    ISNULL(t.tickets, 0)                               AS tickets,
    CASE WHEN ISNULL(t.tickets, 0) > 0
         THEN CAST(ISNULL(sl.revenue, 0) / t.tickets AS DECIMAL(18,4))
         ELSE NULL END                                  AS avg_ticket,
    CAST(ISNULL(st.stock_units,  0) AS DECIMAL(18,4))  AS stock_units,
    CAST(ISNULL(st.stock_value,  0) AS DECIMAL(18,4))  AS stock_value,
    ISNULL(st.skus_in_store,   0)                      AS skus_in_store,
    ISNULL(st.skus_zero_stock, 0)                      AS skus_zero_stock,
    ISNULL(st.skus_obsolete,   0)                      AS skus_obsolete
FROM gold.dim_store ds
JOIN all_months am ON am.tenant_id = ds.tenant_id
LEFT JOIN sales_by_store sl
    ON sl.tenant_id = ds.tenant_id AND sl.store_id = ds.store_id
   AND sl.year_month_iso = am.year_month_iso
LEFT JOIN tickets_by_store t
    ON t.tenant_id = ds.tenant_id AND t.store_id = ds.store_id
   AND t.year_month_iso = am.year_month_iso
LEFT JOIN stock_by_store st
    ON st.tenant_id = ds.tenant_id AND st.store_id = ds.store_id
   AND st.year_month_iso = am.year_month_iso
WHERE ds.is_active = 1;
GO
