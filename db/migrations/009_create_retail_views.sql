/* ============================================================
 * 009_create_retail_views.sql
 *
 * Porta las vistas analiticas retail desde gold.* (SQL Server) a
 * gold_t23.* (PostgreSQL). Mantiene la misma semantica donde es
 * posible. Diferencias documentadas inline cuando una vista depende
 * de dbo.* (tablas del ERP que no se migran).
 *
 * Vistas portadas (8):
 *   vw_sku_coverage_status         (1:1)
 *   vw_sku_velocity_segmented      (1:1)
 *   vw_brand_performance           (1:1)
 *   vw_active_alerts               (1:1, deriva de coverage_status)
 *   vw_action_recommendation_priority (1:1)
 *   vw_sales_monthly               (1:1)
 *   vw_store_dashboard             (adaptada: tickets de fact, no dbo)
 *   vw_store_dashboard_monthly     (adaptada: tickets de fact, no dbo)
 *   vw_brand_performance_monthly   (adaptada: stock mensual desde weekly)
 *
 * Vistas OMITIDAS (dependen de dbo.* del ERP, no aplicables a PG):
 *   vw_sales_pipeline       (dbo.documento)
 *   vw_stock_monthly_eom    (dbo.submayor_inventario + dbo.documento)
 *
 * Idempotente: CREATE OR REPLACE VIEW.
 * ============================================================ */


-- ─────────────────────────────────────────────────────────────
-- vw_sku_coverage_status
-- ─────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW gold_t23.vw_sku_coverage_status AS
WITH latest_week AS (
    SELECT tenant_id, MAX(iso_year_week) AS iso_year_week
    FROM gold_t23.fact_stock_weekly
    GROUP BY tenant_id
),
velocity_4w AS (
    SELECT
        f.tenant_id, f.store_id, f.sku_id,
        CAST(SUM(f.units_sold_net) / 28.0 AS NUMERIC(18,4)) AS units_per_day_4w,
        CAST(SUM(f.revenue_net)            AS NUMERIC(18,4)) AS revenue_4w
    FROM gold_t23.fact_sales_weekly f
    JOIN gold_t23.dim_date dd
        ON dd.iso_year_week = f.iso_year_week AND dd.day_of_week = 7
    WHERE dd.week_end_date >= CURRENT_DATE - INTERVAL '28 days'
    GROUP BY f.tenant_id, f.store_id, f.sku_id
)
SELECT
    s.tenant_id,
    s.iso_year_week,
    s.store_id,
    s.sku_id,
    ds.sku_code,
    ds.sku_name,
    COALESCE(ds.brand_id, 0)                                       AS brand_id,
    COALESCE(ds.brand_name, 'SIN MARCA')                           AS brand_name,
    COALESCE(ds.category_id, 0)                                    AS category_id,
    COALESCE(dst.store_name, 'SIN TIENDA')                         AS store_name,
    s.stock_units,
    s.stock_value,
    s.unit_cost,
    s.has_zero_stock_flag,
    s.is_obsolete_flag,
    s.days_since_last_sale,
    COALESCE(v.units_per_day_4w, 0)                                AS units_per_day_4w,
    CASE
        WHEN COALESCE(v.units_per_day_4w, 0) <= 0 THEN NULL
        ELSE CAST(s.stock_units / v.units_per_day_4w AS NUMERIC(9,2))
    END                                                            AS days_coverage,
    COALESCE(obs_rule.coverage_min_days, 30)                       AS target_min_days,
    COALESCE(obs_rule.coverage_max_days, 90)                       AS target_max_days,
    COALESCE(obs_rule.primary_action,    'REPONER')                AS suggested_action,
    obs_rule.discount_pct                                          AS suggested_discount_pct,
    CASE
        WHEN s.has_zero_stock_flag                       THEN 'RED'
        WHEN s.is_obsolete_flag                          THEN 'RED'
        WHEN COALESCE(v.units_per_day_4w, 0) <= 0        THEN 'GREY'
        WHEN s.stock_units / v.units_per_day_4w
             > COALESCE(obs_rule.coverage_max_days, 90)  THEN 'RED'
        WHEN s.stock_units / v.units_per_day_4w
             < COALESCE(obs_rule.coverage_min_days, 30)  THEN 'YELLOW'
        ELSE                                                  'GREEN'
    END                                                            AS status_color
FROM gold_t23.fact_stock_weekly s
JOIN latest_week lw
    ON lw.tenant_id = s.tenant_id AND lw.iso_year_week = s.iso_year_week
LEFT JOIN gold_t23.dim_sku ds
    ON ds.tenant_id = s.tenant_id AND ds.sku_id = s.sku_id
LEFT JOIN velocity_4w v
    ON v.tenant_id = s.tenant_id AND v.store_id = s.store_id AND v.sku_id = s.sku_id
LEFT JOIN gold_t23.dim_store dst
    ON dst.tenant_id = s.tenant_id AND dst.store_id = s.store_id
LEFT JOIN gold_t23.dim_date dd_w
    ON dd_w.iso_year_week = s.iso_year_week AND dd_w.day_of_week = 7
LEFT JOIN LATERAL (
    SELECT r.coverage_min_days, r.coverage_max_days, r.primary_action, r.discount_pct
    FROM gold_t23.dim_business_rules r
    WHERE r.tenant_id = s.tenant_id
      AND r.is_active
      AND r.rule_id   > 0
      AND (r.brand_id    = 0 OR r.brand_id    = COALESCE(ds.brand_id, 0))
      AND (r.category_id = 0 OR r.category_id = COALESCE(ds.category_id, 0))
      AND (r.season_month IS NULL OR r.season_month = dd_w.season_month)
    ORDER BY
        CASE WHEN r.brand_id     = 0    THEN 1 ELSE 0 END,
        CASE WHEN r.category_id  = 0    THEN 1 ELSE 0 END,
        CASE WHEN r.season_month IS NULL THEN 1 ELSE 0 END,
        r.priority,
        r.rule_id
    LIMIT 1
) obs_rule ON TRUE;


-- ─────────────────────────────────────────────────────────────
-- vw_sku_velocity_segmented (ABCD)
-- ─────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW gold_t23.vw_sku_velocity_segmented AS
WITH last_8w AS (
    SELECT f.tenant_id, f.sku_id,
           SUM(f.units_sold_net) AS units_8w,
           SUM(f.revenue_net)    AS revenue_8w,
           COUNT(DISTINCT f.iso_year_week) AS weeks_with_sales
    FROM gold_t23.fact_sales_weekly f
    JOIN gold_t23.dim_date dd
        ON dd.iso_year_week = f.iso_year_week AND dd.day_of_week = 7
    WHERE dd.week_end_date >= CURRENT_DATE - INTERVAL '56 days'
    GROUP BY f.tenant_id, f.sku_id
),
combined AS (
    SELECT
        ds.tenant_id, ds.sku_id, ds.sku_code, ds.sku_name,
        ds.brand_id, ds.brand_name, ds.category_id,
        CAST(COALESCE(l.units_8w,   0) AS NUMERIC(18,4)) AS units_8w,
        CAST(COALESCE(l.revenue_8w, 0) AS NUMERIC(18,4)) AS revenue_8w,
        COALESCE(l.weeks_with_sales, 0)                  AS weeks_with_sales
    FROM gold_t23.dim_sku ds
    LEFT JOIN last_8w l ON l.tenant_id = ds.tenant_id AND l.sku_id = ds.sku_id
    WHERE ds.is_active AND NOT ds.is_service
)
SELECT
    c.tenant_id, c.sku_id, c.sku_code, c.sku_name,
    c.brand_id, c.brand_name, c.category_id,
    c.units_8w, c.revenue_8w, c.weeks_with_sales,
    CAST(c.units_8w / 56.0 AS NUMERIC(18,4)) AS units_per_day_avg,
    -- CHOOSE() de TSQL -> CASE en PG
    CASE NTILE(4) OVER (
            PARTITION BY c.tenant_id
            ORDER BY c.units_8w DESC, c.sku_id
        )
        WHEN 1 THEN 'A'
        WHEN 2 THEN 'B'
        WHEN 3 THEN 'C'
        WHEN 4 THEN 'D'
    END AS velocity_segment
FROM combined c;


-- ─────────────────────────────────────────────────────────────
-- vw_brand_performance (semanal)
-- ─────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW gold_t23.vw_brand_performance AS
WITH latest_week AS (
    SELECT tenant_id, MAX(iso_year_week) AS iso_year_week
    FROM gold_t23.fact_sales_weekly
    GROUP BY tenant_id
),
brands AS (
    SELECT DISTINCT tenant_id, brand_id, brand_name
    FROM gold_t23.dim_sku
    WHERE is_active
),
sales_by_brand AS (
    SELECT f.tenant_id, f.iso_year_week, f.brand_id,
        SUM(f.units_sold_net) AS units_sold,
        SUM(f.revenue_net)    AS revenue,
        SUM(f.cogs)           AS cogs,
        SUM(f.gross_margin)   AS margin
    FROM gold_t23.fact_sales_weekly f
    JOIN latest_week lw ON lw.tenant_id = f.tenant_id AND lw.iso_year_week = f.iso_year_week
    GROUP BY f.tenant_id, f.iso_year_week, f.brand_id
),
plan_by_brand AS (
    SELECT p.tenant_id, p.iso_year_week, p.brand_id,
        SUM(p.planned_units)   AS planned_units,
        SUM(p.planned_revenue) AS planned_revenue
    FROM gold_t23.fact_sales_plan p
    JOIN latest_week lw ON lw.tenant_id = p.tenant_id AND lw.iso_year_week = p.iso_year_week
    GROUP BY p.tenant_id, p.iso_year_week, p.brand_id
),
stock_by_brand AS (
    SELECT s.tenant_id, s.iso_year_week, ds.brand_id,
        SUM(s.stock_units)                                            AS stock_units,
        SUM(s.stock_value)                                            AS stock_value,
        SUM(CASE WHEN s.has_zero_stock_flag THEN 1 ELSE 0 END)        AS skus_zero_stock,
        SUM(CASE WHEN s.is_obsolete_flag    THEN 1 ELSE 0 END)        AS skus_obsolete,
        COUNT(*)                                                      AS skus_count
    FROM gold_t23.fact_stock_weekly s
    JOIN gold_t23.dim_sku ds ON ds.tenant_id = s.tenant_id AND ds.sku_id = s.sku_id
    JOIN latest_week lw  ON lw.tenant_id = s.tenant_id AND lw.iso_year_week = s.iso_year_week
    GROUP BY s.tenant_id, s.iso_year_week, ds.brand_id
)
SELECT
    b.tenant_id,
    lw.iso_year_week,
    b.brand_id,
    b.brand_name,
    CAST(COALESCE(sb.units_sold, 0)   AS NUMERIC(18,4)) AS units_sold,
    CAST(COALESCE(sb.revenue,    0)   AS NUMERIC(18,4)) AS revenue,
    CAST(COALESCE(sb.cogs,       0)   AS NUMERIC(18,4)) AS cogs,
    CAST(COALESCE(sb.margin,     0)   AS NUMERIC(18,4)) AS gross_margin,
    CASE WHEN COALESCE(sb.revenue, 0) > 0
         THEN CAST(sb.margin / sb.revenue AS NUMERIC(9,4))
         ELSE NULL END                                  AS gross_margin_pct,
    CAST(COALESCE(pb.planned_units,   0) AS NUMERIC(18,4)) AS planned_units,
    CAST(COALESCE(pb.planned_revenue, 0) AS NUMERIC(18,4)) AS planned_revenue,
    CASE WHEN COALESCE(pb.planned_units, 0) > 0
         THEN CAST(COALESCE(sb.units_sold, 0) / pb.planned_units AS NUMERIC(9,4))
         ELSE NULL END                                  AS units_vs_plan_pct,
    CASE WHEN COALESCE(pb.planned_revenue, 0) > 0
         THEN CAST(COALESCE(sb.revenue, 0) / pb.planned_revenue AS NUMERIC(9,4))
         ELSE NULL END                                  AS revenue_vs_plan_pct,
    CAST(COALESCE(stk.stock_units, 0) AS NUMERIC(18,4)) AS stock_units,
    CAST(COALESCE(stk.stock_value, 0) AS NUMERIC(18,4)) AS stock_value,
    COALESCE(stk.skus_count,       0)                  AS skus_count,
    COALESCE(stk.skus_zero_stock,  0)                  AS skus_zero_stock,
    COALESCE(stk.skus_obsolete,    0)                  AS skus_obsolete
FROM brands b
JOIN latest_week lw ON lw.tenant_id = b.tenant_id
LEFT JOIN sales_by_brand sb
    ON sb.tenant_id = b.tenant_id AND sb.brand_id = b.brand_id AND sb.iso_year_week = lw.iso_year_week
LEFT JOIN plan_by_brand pb
    ON pb.tenant_id = b.tenant_id AND pb.brand_id = b.brand_id AND pb.iso_year_week = lw.iso_year_week
LEFT JOIN stock_by_brand stk
    ON stk.tenant_id = b.tenant_id AND stk.brand_id = b.brand_id AND stk.iso_year_week = lw.iso_year_week;


-- ─────────────────────────────────────────────────────────────
-- vw_store_dashboard (semanal)
-- DIFERENCIA vs SS: tickets = SUM(fact_sales_weekly.tickets) en lugar de
--    COUNT(DISTINCT dbo.documento). Aproximacion semi-aditiva pero suficiente
--    para el dashboard semanal — tenant 23 sin dbo.* disponible en PG.
-- ─────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW gold_t23.vw_store_dashboard AS
WITH latest_week AS (
    SELECT tenant_id, MAX(iso_year_week) AS iso_year_week
    FROM gold_t23.fact_sales_weekly
    GROUP BY tenant_id
),
sales_by_store AS (
    SELECT f.tenant_id, f.iso_year_week, f.store_id,
        SUM(f.units_sold_net)   AS units_sold,
        SUM(f.revenue_net)      AS revenue,
        SUM(f.cogs)             AS cogs,
        SUM(f.gross_margin)     AS margin,
        SUM(f.discount_amount)  AS discount,
        SUM(f.tickets)          AS tickets
    FROM gold_t23.fact_sales_weekly f
    JOIN latest_week lw ON lw.tenant_id = f.tenant_id AND lw.iso_year_week = f.iso_year_week
    GROUP BY f.tenant_id, f.iso_year_week, f.store_id
),
stock_by_store AS (
    SELECT s.tenant_id, s.iso_year_week, s.store_id,
        SUM(s.stock_units)                                            AS stock_units,
        SUM(s.stock_value)                                            AS stock_value,
        SUM(CASE WHEN s.has_zero_stock_flag THEN 1 ELSE 0 END)        AS skus_zero_stock,
        SUM(CASE WHEN s.is_obsolete_flag    THEN 1 ELSE 0 END)        AS skus_obsolete,
        COUNT(*)                                                      AS skus_in_store
    FROM gold_t23.fact_stock_weekly s
    JOIN latest_week lw ON lw.tenant_id = s.tenant_id AND lw.iso_year_week = s.iso_year_week
    GROUP BY s.tenant_id, s.iso_year_week, s.store_id
)
SELECT
    ds.tenant_id,
    lw.iso_year_week,
    ds.store_id,
    ds.store_code,
    ds.store_name,
    ds.block_ab,
    ds.is_store_flag,
    CAST(COALESCE(sl.units_sold,  0) AS NUMERIC(18,4)) AS units_sold,
    CAST(COALESCE(sl.revenue,     0) AS NUMERIC(18,4)) AS revenue,
    CAST(COALESCE(sl.cogs,        0) AS NUMERIC(18,4)) AS cogs,
    CAST(COALESCE(sl.margin,      0) AS NUMERIC(18,4)) AS gross_margin,
    CAST(COALESCE(sl.discount,    0) AS NUMERIC(18,4)) AS discount_amount,
    CASE WHEN COALESCE(sl.revenue, 0) > 0
         THEN CAST(sl.margin / sl.revenue AS NUMERIC(9,4))
         ELSE NULL END                              AS gross_margin_pct,
    COALESCE(sl.tickets, 0)                         AS tickets,
    CASE WHEN COALESCE(sl.tickets, 0) > 0
         THEN CAST(sl.revenue / sl.tickets AS NUMERIC(18,4))
         ELSE NULL END                              AS avg_ticket,
    CAST(COALESCE(st.stock_units, 0) AS NUMERIC(18,4)) AS stock_units,
    CAST(COALESCE(st.stock_value, 0) AS NUMERIC(18,4)) AS stock_value,
    COALESCE(st.skus_in_store,   0)                  AS skus_in_store,
    COALESCE(st.skus_zero_stock, 0)                  AS skus_zero_stock,
    COALESCE(st.skus_obsolete,   0)                  AS skus_obsolete
FROM gold_t23.dim_store ds
JOIN latest_week lw ON lw.tenant_id = ds.tenant_id
LEFT JOIN sales_by_store sl
    ON sl.tenant_id = ds.tenant_id AND sl.store_id = ds.store_id AND sl.iso_year_week = lw.iso_year_week
LEFT JOIN stock_by_store st
    ON st.tenant_id = ds.tenant_id AND st.store_id = ds.store_id AND st.iso_year_week = lw.iso_year_week;


-- ─────────────────────────────────────────────────────────────
-- vw_active_alerts
-- Deriva de vw_sku_coverage_status. 4 tipos: STOCK_ZERO, OBSOLETE,
-- OVERSTOCK, UNDERSTOCK. alert_id determinista (no IDENTITY).
-- ─────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW gold_t23.vw_active_alerts AS
WITH base AS (
    SELECT
        cs.tenant_id, cs.iso_year_week, cs.store_id, cs.sku_id,
        cs.brand_id, cs.brand_name, cs.sku_code, cs.sku_name,
        cs.store_name,
        cs.stock_units, cs.stock_value, cs.unit_cost,
        cs.has_zero_stock_flag, cs.is_obsolete_flag,
        cs.days_since_last_sale, cs.days_coverage,
        cs.units_per_day_4w, cs.target_min_days, cs.target_max_days,
        cs.suggested_action, cs.suggested_discount_pct,
        ds.list_price
    FROM gold_t23.vw_sku_coverage_status cs
    LEFT JOIN gold_t23.dim_sku ds
        ON ds.tenant_id = cs.tenant_id AND ds.sku_id = cs.sku_id
),
stock_zero_alerts AS (
    SELECT
        'STOCK_ZERO:' || b.tenant_id || ':' || b.store_id || ':' || b.sku_id || ':' || b.iso_year_week AS alert_id,
        b.tenant_id, b.iso_year_week,
        'SKU'::text                                                AS "level",
        b.store_id, b.sku_id, b.brand_id,
        b.sku_code, b.sku_name, b.brand_name, b.store_name,
        'STOCK_ZERO'::text                                          AS alert_type,
        CASE WHEN b.units_per_day_4w > 0 THEN 'HIGH' ELSE 'MEDIUM' END AS severity,
        b.stock_units                                               AS metric_value,
        CAST(0 AS NUMERIC(18,4))                                    AS threshold,
        b.suggested_action,
        CAST(b.units_per_day_4w * 7 * COALESCE(b.list_price, 0) AS NUMERIC(18,4)) AS estimated_impact_usd
    FROM base b
    WHERE b.has_zero_stock_flag
),
obsolete_alerts AS (
    SELECT
        'OBSOLETE:' || b.tenant_id || ':' || b.store_id || ':' || b.sku_id || ':' || b.iso_year_week AS alert_id,
        b.tenant_id, b.iso_year_week,
        'SKU'::text,
        b.store_id, b.sku_id, b.brand_id,
        b.sku_code, b.sku_name, b.brand_name, b.store_name,
        'OBSOLETE'::text,
        CASE WHEN b.stock_value > 0 THEN 'MEDIUM' ELSE 'LOW' END,
        CAST(b.days_since_last_sale AS NUMERIC(18,4)),
        CAST(COALESCE(b.target_max_days, 90) AS NUMERIC(18,4)),
        'LIQUIDAR'::text,
        b.stock_value
    FROM base b
    WHERE b.is_obsolete_flag AND NOT b.has_zero_stock_flag
),
overstock_alerts AS (
    SELECT
        'OVERSTOCK:' || b.tenant_id || ':' || b.store_id || ':' || b.sku_id || ':' || b.iso_year_week AS alert_id,
        b.tenant_id, b.iso_year_week,
        'SKU'::text,
        b.store_id, b.sku_id, b.brand_id,
        b.sku_code, b.sku_name, b.brand_name, b.store_name,
        'OVERSTOCK'::text,
        CASE WHEN b.days_coverage > 2 * b.target_max_days THEN 'HIGH' ELSE 'MEDIUM' END,
        b.days_coverage,
        CAST(b.target_max_days AS NUMERIC(18,4)),
        'LIQUIDAR'::text,
        CAST((b.stock_units - b.target_max_days * b.units_per_day_4w) * b.unit_cost AS NUMERIC(18,4))
    FROM base b
    WHERE b.units_per_day_4w > 0
      AND b.days_coverage IS NOT NULL
      AND b.days_coverage > b.target_max_days
      AND NOT b.has_zero_stock_flag
      AND NOT b.is_obsolete_flag
),
understock_alerts AS (
    SELECT
        'UNDERSTOCK:' || b.tenant_id || ':' || b.store_id || ':' || b.sku_id || ':' || b.iso_year_week AS alert_id,
        b.tenant_id, b.iso_year_week,
        'SKU'::text,
        b.store_id, b.sku_id, b.brand_id,
        b.sku_code, b.sku_name, b.brand_name, b.store_name,
        'UNDERSTOCK'::text,
        CASE WHEN b.days_coverage < 0.5 * b.target_min_days THEN 'HIGH' ELSE 'MEDIUM' END,
        b.days_coverage,
        CAST(b.target_min_days AS NUMERIC(18,4)),
        'REPONER'::text,
        CAST((b.target_min_days - b.days_coverage) * b.units_per_day_4w
             * COALESCE(b.list_price, 0) * 0.5 AS NUMERIC(18,4))
    FROM base b
    WHERE b.units_per_day_4w > 0
      AND b.days_coverage IS NOT NULL
      AND b.days_coverage < b.target_min_days
      AND NOT b.has_zero_stock_flag
)
SELECT * FROM stock_zero_alerts
UNION ALL
SELECT * FROM obsolete_alerts
UNION ALL
SELECT * FROM overstock_alerts
UNION ALL
SELECT * FROM understock_alerts;


-- ─────────────────────────────────────────────────────────────
-- vw_action_recommendation_priority
-- ─────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW gold_t23.vw_action_recommendation_priority AS
WITH scored AS (
    SELECT
        a.*,
        CASE a.severity WHEN 'HIGH' THEN 3 WHEN 'MEDIUM' THEN 2 ELSE 1 END AS severity_weight,
        CAST(COALESCE(a.estimated_impact_usd, 0) *
             CASE a.severity WHEN 'HIGH' THEN 3 WHEN 'MEDIUM' THEN 2 ELSE 1 END
             AS NUMERIC(18,4))                                            AS priority_score
    FROM gold_t23.vw_active_alerts a
)
SELECT
    s.alert_id, s.tenant_id, s.iso_year_week, s."level",
    s.store_id, s.sku_id, s.brand_id,
    s.sku_code, s.sku_name, s.brand_name, s.store_name,
    s.alert_type, s.severity, s.metric_value, s.threshold,
    s.suggested_action, s.estimated_impact_usd,
    s.severity_weight, s.priority_score,
    ROW_NUMBER() OVER (
        PARTITION BY s.tenant_id
        ORDER BY s.priority_score DESC, s.alert_id
    ) AS priority_rank
FROM scored s;


-- ─────────────────────────────────────────────────────────────
-- vw_sales_monthly (igual semantica que SS)
-- ─────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW gold_t23.vw_sales_monthly AS
SELECT
    f.tenant_id,
    dd.year_month_iso,
    dd.month_id_iso,
    f.store_id,
    f.sku_id,
    f.brand_id,
    f.category_id,
    MAX(f.currency_code)                            AS currency_code,
    CAST(SUM(f.units_sold_gross)  AS NUMERIC(18,4)) AS units_sold_gross,
    CAST(SUM(f.units_returned)    AS NUMERIC(18,4)) AS units_returned,
    CAST(SUM(f.units_sold_net)    AS NUMERIC(18,4)) AS units_sold_net,
    CAST(SUM(f.revenue_gross)     AS NUMERIC(18,4)) AS revenue_gross,
    CAST(SUM(f.revenue_returned)  AS NUMERIC(18,4)) AS revenue_returned,
    CAST(SUM(f.revenue_net)       AS NUMERIC(18,4)) AS revenue_net,
    CAST(SUM(f.cogs)              AS NUMERIC(18,4)) AS cogs,
    CAST(SUM(f.gross_margin)      AS NUMERIC(18,4)) AS gross_margin,
    CASE WHEN SUM(f.revenue_net) > 0
         THEN CAST(SUM(f.gross_margin) / SUM(f.revenue_net) AS NUMERIC(9,4))
         ELSE NULL END                              AS gross_margin_pct,
    SUM(f.tickets)                                  AS tickets,
    CAST(SUM(f.discount_amount)   AS NUMERIC(18,4)) AS discount_amount
FROM gold_t23.fact_sales_weekly f
JOIN gold_t23.dim_date dd
    ON dd.iso_year_week = f.iso_year_week AND dd.day_of_week = 4
GROUP BY
    f.tenant_id, dd.year_month_iso, dd.month_id_iso,
    f.store_id, f.sku_id, f.brand_id, f.category_id;


-- ─────────────────────────────────────────────────────────────
-- vw_brand_performance_monthly
-- DIFERENCIA vs SS: stock_by_brand sale del ultimo iso_year_week del mes
--    en fact_stock_weekly (no de un EOM exacto via dbo.submayor_inventario).
--    Aproximacion suficiente para el panel mensual; documentado.
-- ─────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW gold_t23.vw_brand_performance_monthly AS
WITH brands AS (
    SELECT DISTINCT tenant_id, brand_id, brand_name
    FROM gold_t23.dim_sku
    WHERE is_active
),
all_months AS (
    SELECT DISTINCT tenant_id, year_month_iso, month_id_iso
    FROM gold_t23.vw_sales_monthly
),
sales_by_brand AS (
    SELECT
        tenant_id, year_month_iso, month_id_iso, brand_id,
        SUM(units_sold_net)  AS units_sold,
        SUM(revenue_net)     AS revenue,
        SUM(cogs)            AS cogs,
        SUM(gross_margin)    AS gross_margin
    FROM gold_t23.vw_sales_monthly
    GROUP BY tenant_id, year_month_iso, month_id_iso, brand_id
),
plan_by_brand AS (
    SELECT
        p.tenant_id,
        dd.year_month_iso,
        p.brand_id,
        SUM(p.planned_units)   AS planned_units,
        SUM(p.planned_revenue) AS planned_revenue
    FROM gold_t23.fact_sales_plan p
    JOIN gold_t23.dim_date dd
        ON dd.iso_year_week = p.iso_year_week AND dd.day_of_week = 4
    GROUP BY p.tenant_id, dd.year_month_iso, p.brand_id
),
-- Aprox de stock EOM: ultimo iso_year_week dentro de cada mes
month_last_week AS (
    SELECT tenant_id, year_month_iso, MAX(iso_year_week) AS iso_year_week
    FROM (
        SELECT DISTINCT s.tenant_id, dd.year_month_iso, s.iso_year_week
        FROM gold_t23.fact_stock_weekly s
        JOIN gold_t23.dim_date dd
            ON dd.iso_year_week = s.iso_year_week AND dd.day_of_week = 7
    ) x
    GROUP BY tenant_id, year_month_iso
),
stock_by_brand AS (
    SELECT
        s.tenant_id, mlw.year_month_iso, ds.brand_id,
        SUM(s.stock_units)                                          AS stock_units,
        SUM(s.stock_value)                                          AS stock_value,
        SUM(CASE WHEN s.has_zero_stock_flag THEN 1 ELSE 0 END)      AS skus_zero_stock,
        SUM(CASE WHEN s.is_obsolete_flag    THEN 1 ELSE 0 END)      AS skus_obsolete,
        COUNT(*)                                                    AS skus_count
    FROM gold_t23.fact_stock_weekly s
    JOIN month_last_week mlw
        ON mlw.tenant_id = s.tenant_id AND mlw.iso_year_week = s.iso_year_week
    JOIN gold_t23.dim_sku ds ON ds.tenant_id = s.tenant_id AND ds.sku_id = s.sku_id
    GROUP BY s.tenant_id, mlw.year_month_iso, ds.brand_id
)
SELECT
    b.tenant_id,
    am.year_month_iso,
    am.month_id_iso,
    b.brand_id,
    b.brand_name,
    CAST(COALESCE(sb.units_sold,  0) AS NUMERIC(18,4)) AS units_sold,
    CAST(COALESCE(sb.revenue,     0) AS NUMERIC(18,4)) AS revenue,
    CAST(COALESCE(sb.cogs,        0) AS NUMERIC(18,4)) AS cogs,
    CAST(COALESCE(sb.gross_margin,0) AS NUMERIC(18,4)) AS gross_margin,
    CASE WHEN COALESCE(sb.revenue, 0) > 0
         THEN CAST(COALESCE(sb.gross_margin, 0) / sb.revenue AS NUMERIC(9,4))
         ELSE NULL END                                AS gross_margin_pct,
    CAST(COALESCE(pb.planned_units,   0) AS NUMERIC(18,4)) AS planned_units,
    CAST(COALESCE(pb.planned_revenue, 0) AS NUMERIC(18,4)) AS planned_revenue,
    CASE WHEN COALESCE(pb.planned_units, 0) > 0
         THEN CAST(COALESCE(sb.units_sold, 0) / pb.planned_units AS NUMERIC(9,4))
         ELSE NULL END                                AS units_vs_plan_pct,
    CASE WHEN COALESCE(pb.planned_revenue, 0) > 0
         THEN CAST(COALESCE(sb.revenue, 0) / pb.planned_revenue AS NUMERIC(9,4))
         ELSE NULL END                                AS revenue_vs_plan_pct,
    CAST(COALESCE(stk.stock_units, 0) AS NUMERIC(18,4)) AS stock_units,
    CAST(COALESCE(stk.stock_value, 0) AS NUMERIC(18,4)) AS stock_value,
    COALESCE(stk.skus_count,       0)                  AS skus_count,
    COALESCE(stk.skus_zero_stock,  0)                  AS skus_zero_stock,
    COALESCE(stk.skus_obsolete,    0)                  AS skus_obsolete
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


-- ─────────────────────────────────────────────────────────────
-- vw_store_dashboard_monthly
-- DIFERENCIA vs SS: tickets = SUM(fact_sales_weekly.tickets) por mes
--    (semi-aditivo en bordes de mes). Stock: ultimo iso_year_week del mes.
-- ─────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW gold_t23.vw_store_dashboard_monthly AS
WITH all_months AS (
    SELECT DISTINCT tenant_id, year_month_iso, month_id_iso
    FROM gold_t23.vw_sales_monthly
),
sales_by_store AS (
    SELECT
        tenant_id, year_month_iso, month_id_iso, store_id,
        SUM(units_sold_net)   AS units_sold,
        SUM(revenue_net)      AS revenue,
        SUM(cogs)             AS cogs,
        SUM(gross_margin)     AS gross_margin,
        SUM(discount_amount)  AS discount_amount,
        SUM(tickets)          AS tickets
    FROM gold_t23.vw_sales_monthly
    GROUP BY tenant_id, year_month_iso, month_id_iso, store_id
),
month_last_week AS (
    SELECT tenant_id, year_month_iso, MAX(iso_year_week) AS iso_year_week
    FROM (
        SELECT DISTINCT s.tenant_id, dd.year_month_iso, s.iso_year_week
        FROM gold_t23.fact_stock_weekly s
        JOIN gold_t23.dim_date dd
            ON dd.iso_year_week = s.iso_year_week AND dd.day_of_week = 7
    ) x
    GROUP BY tenant_id, year_month_iso
),
stock_by_store AS (
    SELECT
        s.tenant_id, mlw.year_month_iso, s.store_id,
        SUM(s.stock_units)                                          AS stock_units,
        SUM(s.stock_value)                                          AS stock_value,
        SUM(CASE WHEN s.has_zero_stock_flag THEN 1 ELSE 0 END)      AS skus_zero_stock,
        SUM(CASE WHEN s.is_obsolete_flag    THEN 1 ELSE 0 END)      AS skus_obsolete,
        COUNT(*)                                                    AS skus_in_store
    FROM gold_t23.fact_stock_weekly s
    JOIN month_last_week mlw
        ON mlw.tenant_id = s.tenant_id AND mlw.iso_year_week = s.iso_year_week
    GROUP BY s.tenant_id, mlw.year_month_iso, s.store_id
)
SELECT
    ds.tenant_id,
    am.year_month_iso,
    am.month_id_iso,
    ds.store_id,
    ds.store_code,
    ds.store_name,
    ds.block_ab,
    ds.is_store_flag,
    CAST(COALESCE(sl.units_sold,    0) AS NUMERIC(18,4)) AS units_sold,
    CAST(COALESCE(sl.revenue,       0) AS NUMERIC(18,4)) AS revenue,
    CAST(COALESCE(sl.cogs,          0) AS NUMERIC(18,4)) AS cogs,
    CAST(COALESCE(sl.gross_margin,  0) AS NUMERIC(18,4)) AS gross_margin,
    CAST(COALESCE(sl.discount_amount,0) AS NUMERIC(18,4)) AS discount_amount,
    CASE WHEN COALESCE(sl.revenue, 0) > 0
         THEN CAST(COALESCE(sl.gross_margin, 0) / sl.revenue AS NUMERIC(9,4))
         ELSE NULL END                                  AS gross_margin_pct,
    COALESCE(sl.tickets, 0)                            AS tickets,
    CASE WHEN COALESCE(sl.tickets, 0) > 0
         THEN CAST(COALESCE(sl.revenue, 0) / sl.tickets AS NUMERIC(18,4))
         ELSE NULL END                                  AS avg_ticket,
    CAST(COALESCE(st.stock_units,  0) AS NUMERIC(18,4))  AS stock_units,
    CAST(COALESCE(st.stock_value,  0) AS NUMERIC(18,4))  AS stock_value,
    COALESCE(st.skus_in_store,   0)                      AS skus_in_store,
    COALESCE(st.skus_zero_stock, 0)                      AS skus_zero_stock,
    COALESCE(st.skus_obsolete,   0)                      AS skus_obsolete
FROM gold_t23.dim_store ds
JOIN all_months am ON am.tenant_id = ds.tenant_id
LEFT JOIN sales_by_store sl
    ON sl.tenant_id = ds.tenant_id AND sl.store_id = ds.store_id
   AND sl.year_month_iso = am.year_month_iso
LEFT JOIN stock_by_store st
    ON st.tenant_id = ds.tenant_id AND st.store_id = ds.store_id
   AND st.year_month_iso = am.year_month_iso;
