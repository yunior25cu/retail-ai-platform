/* ============================================================
 * BLOQUE 7 — 7 Vistas analiticas Gold+
 * Convencion: vw_* (todas VIEW, NO indexed view).
 * Multi-tenant: cada view expone tenant_id, NO filtra internamente.
 *               Consumer hace WHERE tenant_id = X.
 * Brand/category: SIEMPRE via gold.dim_sku.sku_id (nunca por sku_code).
 * Filtro estado: =2 normal (estado=1 SOLO en vw_sales_pipeline).
 * Tiebreakers: orden determinista en TOP 1 / NTILE.
 * ============================================================ */

------------------------------------------------------------------
-- 7.1 gold.vw_sales_pipeline
--     Documentos de venta (tipo_documento=3) en BORRADOR (estado=1).
--     Unico view que muestra estado=1 (excluido de los facts).
------------------------------------------------------------------
IF OBJECT_ID('gold.vw_sales_pipeline','V') IS NOT NULL DROP VIEW gold.vw_sales_pipeline;
GO
CREATE VIEW gold.vw_sales_pipeline AS
SELECT
    d.id_empresa                                                                  AS tenant_id,
    d.id                                                                          AS document_id,
    d.numero                                                                      AS document_number,
    d.fecha_emision                                                               AS document_date,
    d.id_almacen                                                                  AS store_id,
    d.id_socio_comercial                                                          AS partner_id,
    CAST(d.importe_base       AS DECIMAL(18,4))                                   AS amount_base,
    CAST(d.importe_total_base AS DECIMAL(18,4))                                   AS amount_total_base,
    (SELECT COUNT(*)
       FROM dbo.documento_producto dp WHERE dp.id_documento = d.id)               AS line_count,
    CAST((SELECT SUM(dp.cantidad)
            FROM dbo.documento_producto dp WHERE dp.id_documento = d.id)
         AS DECIMAL(18,4))                                                        AS total_units,
    d.created_at,
    d.updated_at,
    DATEDIFF(DAY, d.fecha_emision, CAST(SYSUTCDATETIME() AS DATE))                AS days_in_pipeline
FROM dbo.documento d
WHERE d.tipo_documento = 3       -- factura de venta
  AND d.estado         = 1       -- borrador (UNICO view que permite estado=1)
  AND d.[delete]       = 0;
GO

------------------------------------------------------------------
-- 7.2 gold.vw_sku_coverage_status
--     Semaforo de cobertura por (tenant, store, sku) en la ULTIMA semana
--     de fact_stock_weekly de cada tenant. Aplica dim_business_rules con
--     resolucion de especificidad (brand+cat+season > priority > rule_id).
--     Velocidad: SUM(units_sold_net) / 28 de las ultimas 4 semanas.
--     Defaults si no hay regla: cov_min=30, cov_max=90, action=REPONER.
------------------------------------------------------------------
IF OBJECT_ID('gold.vw_sku_coverage_status','V') IS NOT NULL DROP VIEW gold.vw_sku_coverage_status;
GO
CREATE VIEW gold.vw_sku_coverage_status AS
WITH latest_week AS (
    SELECT tenant_id, MAX(iso_year_week) AS iso_year_week
    FROM gold.fact_stock_weekly
    GROUP BY tenant_id
),
velocity_4w AS (
    /* Velocidad por (tenant, store, sku) ultimas 4 semanas calendario */
    SELECT
        f.tenant_id, f.store_id, f.sku_id,
        CAST(SUM(f.units_sold_net) / 28.0 AS DECIMAL(18,4)) AS units_per_day_4w,
        CAST(SUM(f.revenue_net)            AS DECIMAL(18,4)) AS revenue_4w
    FROM gold.fact_sales_weekly f
    JOIN gold.dim_date dd
        ON dd.iso_year_week = f.iso_year_week AND dd.day_of_week = 7
    WHERE dd.week_end_date >= DATEADD(DAY, -28, CAST(SYSUTCDATETIME() AS DATE))
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
    COALESCE(ds.brand_name, N'SIN MARCA')                          AS brand_name,
    COALESCE(ds.category_id, 0)                                    AS category_id,
    COALESCE(dst.store_name, N'SIN TIENDA')                          AS store_name,
    s.stock_units,
    s.stock_value,
    s.unit_cost,
    s.has_zero_stock_flag,
    s.is_obsolete_flag,
    s.days_since_last_sale,
    COALESCE(v.units_per_day_4w, 0)                                AS units_per_day_4w,
    CASE
        WHEN COALESCE(v.units_per_day_4w, 0) <= 0 THEN NULL
        ELSE CAST(s.stock_units / v.units_per_day_4w AS DECIMAL(9,2))
    END                                                            AS days_coverage,
    ISNULL(obs_rule.coverage_min_days, 30)                         AS target_min_days,
    ISNULL(obs_rule.coverage_max_days, 90)                         AS target_max_days,
    ISNULL(obs_rule.primary_action,    N'REPONER')                 AS suggested_action,
    obs_rule.discount_pct                                          AS suggested_discount_pct,
    CASE
        WHEN s.has_zero_stock_flag = 1                          THEN N'RED'        -- quiebre
        WHEN s.is_obsolete_flag    = 1                          THEN N'RED'        -- obsoleto
        WHEN COALESCE(v.units_per_day_4w, 0) <= 0               THEN N'GREY'       -- sin velocidad
        WHEN s.stock_units / v.units_per_day_4w
             > ISNULL(obs_rule.coverage_max_days, 90)           THEN N'RED'        -- sobrestock
        WHEN s.stock_units / v.units_per_day_4w
             < ISNULL(obs_rule.coverage_min_days, 30)           THEN N'YELLOW'     -- escaso
        ELSE                                                         N'GREEN'
    END                                                            AS status_color
FROM gold.fact_stock_weekly s
JOIN latest_week lw
    ON lw.tenant_id = s.tenant_id AND lw.iso_year_week = s.iso_year_week
LEFT JOIN gold.dim_sku ds
    ON ds.tenant_id = s.tenant_id AND ds.sku_id = s.sku_id
LEFT JOIN velocity_4w v
    ON v.tenant_id = s.tenant_id AND v.store_id = s.store_id AND v.sku_id = s.sku_id
LEFT JOIN gold.dim_store dst
    ON dst.tenant_id = s.tenant_id AND dst.store_id = s.store_id
LEFT JOIN gold.dim_date dd_w
    ON dd_w.iso_year_week = s.iso_year_week AND dd_w.day_of_week = 7
OUTER APPLY (
    SELECT TOP 1 r.coverage_min_days, r.coverage_max_days, r.primary_action, r.discount_pct
    FROM gold.dim_business_rules r
    WHERE r.tenant_id = s.tenant_id
      AND r.is_active = 1
      AND r.rule_id   > 0
      AND (r.brand_id    = 0 OR r.brand_id    = COALESCE(ds.brand_id, 0))
      AND (r.category_id = 0 OR r.category_id = COALESCE(ds.category_id, 0))
      AND (r.season_month IS NULL OR r.season_month = dd_w.season_month)
    ORDER BY
        CASE WHEN r.brand_id     = 0    THEN 1 ELSE 0 END,
        CASE WHEN r.category_id  = 0    THEN 1 ELSE 0 END,
        CASE WHEN r.season_month IS NULL THEN 1 ELSE 0 END,
        r.priority,
        r.rule_id                                          -- tiebreaker determinista
) obs_rule;
GO

------------------------------------------------------------------
-- 7.3 gold.vw_sku_velocity_segmented
--     Segmentacion ABCD por cuartiles de unidades vendidas ultimas 8 semanas.
--     Granularidad: 1 fila por (tenant, sku). Incluye SKUs sin ventas (=> 'D').
--     Base = gold.dim_sku (activos, no servicios). LEFT JOIN ventas.
------------------------------------------------------------------
IF OBJECT_ID('gold.vw_sku_velocity_segmented','V') IS NOT NULL DROP VIEW gold.vw_sku_velocity_segmented;
GO
CREATE VIEW gold.vw_sku_velocity_segmented AS
WITH last_8w AS (
    SELECT f.tenant_id, f.sku_id,
           SUM(f.units_sold_net) AS units_8w,
           SUM(f.revenue_net)    AS revenue_8w,
           COUNT(DISTINCT f.iso_year_week) AS weeks_with_sales
    FROM gold.fact_sales_weekly f
    JOIN gold.dim_date dd
        ON dd.iso_year_week = f.iso_year_week AND dd.day_of_week = 7
    WHERE dd.week_end_date >= DATEADD(DAY, -56, CAST(SYSUTCDATETIME() AS DATE))
    GROUP BY f.tenant_id, f.sku_id
),
combined AS (
    SELECT
        ds.tenant_id, ds.sku_id, ds.sku_code, ds.sku_name,
        ds.brand_id, ds.brand_name, ds.category_id,
        CAST(ISNULL(l.units_8w,   0) AS DECIMAL(18,4)) AS units_8w,
        CAST(ISNULL(l.revenue_8w, 0) AS DECIMAL(18,4)) AS revenue_8w,
        ISNULL(l.weeks_with_sales, 0)                  AS weeks_with_sales
    FROM gold.dim_sku ds
    LEFT JOIN last_8w l ON l.tenant_id = ds.tenant_id AND l.sku_id = ds.sku_id
    WHERE ds.is_active = 1 AND ds.is_service = 0
)
SELECT
    c.tenant_id, c.sku_id, c.sku_code, c.sku_name,
    c.brand_id, c.brand_name, c.category_id,
    c.units_8w, c.revenue_8w, c.weeks_with_sales,
    CAST(c.units_8w / 56.0 AS DECIMAL(18,4)) AS units_per_day_avg,
    /* NTILE: zeros caen naturalmente al ultimo cuartil por sort DESC + tiebreaker */
    CHOOSE(
        NTILE(4) OVER (
            PARTITION BY c.tenant_id
            ORDER BY c.units_8w DESC, c.sku_id        -- tiebreaker sku_id
        ),
        N'A', N'B', N'C', N'D'
    ) AS velocity_segment
FROM combined c;
GO

------------------------------------------------------------------
-- 7.4 gold.vw_store_dashboard
--     KPIs ultima semana por tienda. Base = dim_store (activas).
--     Tickets calculados con COUNT(DISTINCT) directo (no SUM del fact),
--     evitando el sobre-conteo semiaditivo documentado en 6.1.
------------------------------------------------------------------
IF OBJECT_ID('gold.vw_store_dashboard','V') IS NOT NULL DROP VIEW gold.vw_store_dashboard;
GO
CREATE VIEW gold.vw_store_dashboard AS
WITH latest_week AS (
    SELECT tenant_id, MAX(iso_year_week) AS iso_year_week
    FROM gold.fact_sales_weekly
    GROUP BY tenant_id
),
sales_by_store AS (
    SELECT f.tenant_id, f.iso_year_week, f.store_id,
        SUM(f.units_sold_net) AS units_sold,
        SUM(f.revenue_net)    AS revenue,
        SUM(f.cogs)           AS cogs,
        SUM(f.gross_margin)   AS margin,
        SUM(f.discount_amount) AS discount
    FROM gold.fact_sales_weekly f
    JOIN latest_week lw ON lw.tenant_id = f.tenant_id AND lw.iso_year_week = f.iso_year_week
    GROUP BY f.tenant_id, f.iso_year_week, f.store_id
),
tickets_by_store AS (
    /* COUNT(DISTINCT factura) directo desde documento — evita el SUM(tickets) bug */
    SELECT d.id_empresa AS tenant_id, dd.iso_year_week, d.id_almacen AS store_id,
        COUNT(DISTINCT d.id) AS tickets
    FROM dbo.documento d
    JOIN gold.dim_date dd ON dd.[date] = d.fecha_emision
    JOIN latest_week lw   ON lw.tenant_id = d.id_empresa AND lw.iso_year_week = dd.iso_year_week
    WHERE d.tipo_documento = 3
      AND d.estado         IN (1, 2)         -- consistente con el filtro de fact_sales_weekly (Bloque 6.1)
      AND d.[delete]       = 0
    GROUP BY d.id_empresa, dd.iso_year_week, d.id_almacen
),
stock_by_store AS (
    SELECT s.tenant_id, s.iso_year_week, s.store_id,
        SUM(s.stock_units)                       AS stock_units,
        SUM(s.stock_value)                       AS stock_value,
        SUM(CAST(s.has_zero_stock_flag AS INT))  AS skus_zero_stock,
        SUM(CAST(s.is_obsolete_flag    AS INT))  AS skus_obsolete,
        COUNT(*)                                 AS skus_in_store
    FROM gold.fact_stock_weekly s
    JOIN latest_week lw ON lw.tenant_id = s.tenant_id AND lw.iso_year_week = s.iso_year_week
    GROUP BY s.tenant_id, s.iso_year_week, s.store_id
)
SELECT
    ds.tenant_id,
    lw.iso_year_week,
    ds.store_id,
    ds.store_code,
    ds.store_name,
    ds.block_AB,
    ds.is_store_flag,
    CAST(ISNULL(sl.units_sold,  0) AS DECIMAL(18,4)) AS units_sold,
    CAST(ISNULL(sl.revenue,     0) AS DECIMAL(18,4)) AS revenue,
    CAST(ISNULL(sl.cogs,        0) AS DECIMAL(18,4)) AS cogs,
    CAST(ISNULL(sl.margin,      0) AS DECIMAL(18,4)) AS gross_margin,
    CAST(ISNULL(sl.discount,    0) AS DECIMAL(18,4)) AS discount_amount,
    CASE WHEN ISNULL(sl.revenue, 0) > 0
         THEN CAST(sl.margin / sl.revenue AS DECIMAL(9,4))
         ELSE NULL END                              AS gross_margin_pct,
    ISNULL(t.tickets, 0)                            AS tickets,
    CASE WHEN ISNULL(t.tickets, 0) > 0
         THEN CAST(sl.revenue / t.tickets AS DECIMAL(18,4))
         ELSE NULL END                              AS avg_ticket,
    CAST(ISNULL(st.stock_units,  0) AS DECIMAL(18,4)) AS stock_units,
    CAST(ISNULL(st.stock_value,  0) AS DECIMAL(18,4)) AS stock_value,
    ISNULL(st.skus_in_store,   0)                   AS skus_in_store,
    ISNULL(st.skus_zero_stock, 0)                   AS skus_zero_stock,
    ISNULL(st.skus_obsolete,   0)                   AS skus_obsolete
FROM gold.dim_store ds
JOIN latest_week lw
    ON lw.tenant_id = ds.tenant_id
LEFT JOIN sales_by_store sl
    ON sl.tenant_id = ds.tenant_id AND sl.store_id = ds.store_id AND sl.iso_year_week = lw.iso_year_week
LEFT JOIN tickets_by_store t
    ON t.tenant_id = ds.tenant_id AND t.store_id = ds.store_id AND t.iso_year_week = lw.iso_year_week
LEFT JOIN stock_by_store st
    ON st.tenant_id = ds.tenant_id AND st.store_id = ds.store_id AND st.iso_year_week = lw.iso_year_week
WHERE ds.is_active = 1;
GO

------------------------------------------------------------------
-- 7.5 gold.vw_brand_performance
--     KPIs ultima semana por marca + comparacion vs plan.
--     Base = brands distintas en dim_sku (incluye marcas sin venta esta sem).
------------------------------------------------------------------
IF OBJECT_ID('gold.vw_brand_performance','V') IS NOT NULL DROP VIEW gold.vw_brand_performance;
GO
CREATE VIEW gold.vw_brand_performance AS
WITH latest_week AS (
    SELECT tenant_id, MAX(iso_year_week) AS iso_year_week
    FROM gold.fact_sales_weekly
    GROUP BY tenant_id
),
brands AS (
    SELECT DISTINCT tenant_id, brand_id, brand_name
    FROM gold.dim_sku
    WHERE is_active = 1
),
sales_by_brand AS (
    SELECT f.tenant_id, f.iso_year_week, f.brand_id,
        SUM(f.units_sold_net) AS units_sold,
        SUM(f.revenue_net)    AS revenue,
        SUM(f.cogs)           AS cogs,
        SUM(f.gross_margin)   AS margin
    FROM gold.fact_sales_weekly f
    JOIN latest_week lw ON lw.tenant_id = f.tenant_id AND lw.iso_year_week = f.iso_year_week
    GROUP BY f.tenant_id, f.iso_year_week, f.brand_id
),
plan_by_brand AS (
    SELECT p.tenant_id, p.iso_year_week, p.brand_id,
        SUM(p.planned_units)   AS planned_units,
        SUM(p.planned_revenue) AS planned_revenue
    FROM gold.fact_sales_plan p
    JOIN latest_week lw ON lw.tenant_id = p.tenant_id AND lw.iso_year_week = p.iso_year_week
    GROUP BY p.tenant_id, p.iso_year_week, p.brand_id
),
stock_by_brand AS (
    /* JOIN dim_sku para mapear sku_id -> brand_id */
    SELECT s.tenant_id, s.iso_year_week, ds.brand_id,
        SUM(s.stock_units)                      AS stock_units,
        SUM(s.stock_value)                      AS stock_value,
        SUM(CAST(s.has_zero_stock_flag AS INT)) AS skus_zero_stock,
        SUM(CAST(s.is_obsolete_flag    AS INT)) AS skus_obsolete,
        COUNT(*)                                AS skus_count
    FROM gold.fact_stock_weekly s
    JOIN gold.dim_sku ds ON ds.tenant_id = s.tenant_id AND ds.sku_id = s.sku_id
    JOIN latest_week lw  ON lw.tenant_id = s.tenant_id AND lw.iso_year_week = s.iso_year_week
    GROUP BY s.tenant_id, s.iso_year_week, ds.brand_id
)
SELECT
    b.tenant_id,
    lw.iso_year_week,
    b.brand_id,
    b.brand_name,
    CAST(ISNULL(sb.units_sold, 0)   AS DECIMAL(18,4)) AS units_sold,
    CAST(ISNULL(sb.revenue,    0)   AS DECIMAL(18,4)) AS revenue,
    CAST(ISNULL(sb.cogs,       0)   AS DECIMAL(18,4)) AS cogs,
    CAST(ISNULL(sb.margin,     0)   AS DECIMAL(18,4)) AS gross_margin,
    CASE WHEN ISNULL(sb.revenue, 0) > 0
         THEN CAST(sb.margin / sb.revenue AS DECIMAL(9,4))
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
    ISNULL(stk.skus_count,       0)                  AS skus_count,
    ISNULL(stk.skus_zero_stock,  0)                  AS skus_zero_stock,
    ISNULL(stk.skus_obsolete,    0)                  AS skus_obsolete
FROM brands b
JOIN latest_week lw       ON lw.tenant_id = b.tenant_id
LEFT JOIN sales_by_brand sb
    ON sb.tenant_id = b.tenant_id AND sb.brand_id = b.brand_id AND sb.iso_year_week = lw.iso_year_week
LEFT JOIN plan_by_brand pb
    ON pb.tenant_id = b.tenant_id AND pb.brand_id = b.brand_id AND pb.iso_year_week = lw.iso_year_week
LEFT JOIN stock_by_brand stk
    ON stk.tenant_id = b.tenant_id AND stk.brand_id = b.brand_id AND stk.iso_year_week = lw.iso_year_week;
GO

------------------------------------------------------------------
-- 7.6 gold.vw_active_alerts
--     Alertas accionables generadas a partir de vw_sku_coverage_status.
--     Tipos: STOCK_ZERO, OBSOLETE, OVERSTOCK, UNDERSTOCK.
--     alert_id: clave composita determinista (no IDENTITY).
--     estimated_impact_usd: heuristica POC (no precio dinamico).
------------------------------------------------------------------
IF OBJECT_ID('gold.vw_active_alerts','V') IS NOT NULL DROP VIEW gold.vw_active_alerts;
GO
CREATE VIEW gold.vw_active_alerts AS
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
    FROM gold.vw_sku_coverage_status cs
    LEFT JOIN gold.dim_sku ds
        ON ds.tenant_id = cs.tenant_id AND ds.sku_id = cs.sku_id
),
stock_zero_alerts AS (
    SELECT
        CONCAT(N'STOCK_ZERO:', CAST(b.tenant_id AS NVARCHAR(20)),
               N':', CAST(b.store_id AS NVARCHAR(20)),
               N':', CAST(b.sku_id   AS NVARCHAR(20)),
               N':', b.iso_year_week)                             AS alert_id,
        b.tenant_id, b.iso_year_week,
        N'SKU'                                                    AS [level],
        b.store_id, b.sku_id, b.brand_id,
        b.sku_code, b.sku_name, b.brand_name, b.store_name,
        N'STOCK_ZERO'                                             AS alert_type,
        CASE WHEN b.units_per_day_4w > 0 THEN N'HIGH' ELSE N'MEDIUM' END AS severity,
        b.stock_units                                             AS metric_value,
        CAST(0 AS DECIMAL(18,4))                                  AS threshold,
        b.suggested_action,
        /* impacto = ventas perdidas proximos 7 dias a precio de lista */
        CAST(b.units_per_day_4w * 7 * ISNULL(b.list_price, 0) AS DECIMAL(18,4)) AS estimated_impact_usd
    FROM base b
    WHERE b.has_zero_stock_flag = 1
),
obsolete_alerts AS (
    SELECT
        CONCAT(N'OBSOLETE:', CAST(b.tenant_id AS NVARCHAR(20)),
               N':', CAST(b.store_id AS NVARCHAR(20)),
               N':', CAST(b.sku_id   AS NVARCHAR(20)),
               N':', b.iso_year_week)                             AS alert_id,
        b.tenant_id, b.iso_year_week,
        N'SKU'                                                    AS [level],
        b.store_id, b.sku_id, b.brand_id,
        b.sku_code, b.sku_name, b.brand_name, b.store_name,
        N'OBSOLETE'                                               AS alert_type,
        CASE WHEN b.stock_value > 0 THEN N'MEDIUM' ELSE N'LOW' END AS severity,
        CAST(b.days_since_last_sale AS DECIMAL(18,4))             AS metric_value,
        CAST(ISNULL(b.target_max_days, 90) AS DECIMAL(18,4))      AS threshold,
        N'LIQUIDAR'                                               AS suggested_action,
        /* impacto = capital inmovilizado (valor de stock) */
        b.stock_value                                             AS estimated_impact_usd
    FROM base b
    WHERE b.is_obsolete_flag = 1 AND b.has_zero_stock_flag = 0
),
overstock_alerts AS (
    SELECT
        CONCAT(N'OVERSTOCK:', CAST(b.tenant_id AS NVARCHAR(20)),
               N':', CAST(b.store_id AS NVARCHAR(20)),
               N':', CAST(b.sku_id   AS NVARCHAR(20)),
               N':', b.iso_year_week)                             AS alert_id,
        b.tenant_id, b.iso_year_week,
        N'SKU'                                                    AS [level],
        b.store_id, b.sku_id, b.brand_id,
        b.sku_code, b.sku_name, b.brand_name, b.store_name,
        N'OVERSTOCK'                                              AS alert_type,
        CASE WHEN b.days_coverage > 2 * b.target_max_days THEN N'HIGH' ELSE N'MEDIUM' END AS severity,
        b.days_coverage                                           AS metric_value,
        CAST(b.target_max_days AS DECIMAL(18,4))                  AS threshold,
        /* OVERSTOCK siempre sugiere LIQUIDAR, independiente de la regla
           aplicable (que puede decir REPONER pensando en cobertura normal). */
        N'LIQUIDAR'                                               AS suggested_action,
        /* impacto = capital extra inmovilizado vs target */
        CAST((b.stock_units - b.target_max_days * b.units_per_day_4w) * b.unit_cost AS DECIMAL(18,4)) AS estimated_impact_usd
    FROM base b
    WHERE b.units_per_day_4w > 0
      AND b.days_coverage IS NOT NULL
      AND b.days_coverage > b.target_max_days
      AND b.has_zero_stock_flag = 0
      AND b.is_obsolete_flag    = 0
),
understock_alerts AS (
    SELECT
        CONCAT(N'UNDERSTOCK:', CAST(b.tenant_id AS NVARCHAR(20)),
               N':', CAST(b.store_id AS NVARCHAR(20)),
               N':', CAST(b.sku_id   AS NVARCHAR(20)),
               N':', b.iso_year_week)                             AS alert_id,
        b.tenant_id, b.iso_year_week,
        N'SKU'                                                    AS [level],
        b.store_id, b.sku_id, b.brand_id,
        b.sku_code, b.sku_name, b.brand_name, b.store_name,
        N'UNDERSTOCK'                                             AS alert_type,
        CASE WHEN b.days_coverage < 0.5 * b.target_min_days THEN N'HIGH' ELSE N'MEDIUM' END AS severity,
        b.days_coverage                                           AS metric_value,
        CAST(b.target_min_days AS DECIMAL(18,4))                  AS threshold,
        N'REPONER'                                                AS suggested_action,
        /* impacto = ventas perdidas estimadas (gap dias * velocidad * precio * 0.5 conservador) */
        CAST((b.target_min_days - b.days_coverage) * b.units_per_day_4w
             * ISNULL(b.list_price, 0) * 0.5 AS DECIMAL(18,4))    AS estimated_impact_usd
    FROM base b
    WHERE b.units_per_day_4w > 0
      AND b.days_coverage IS NOT NULL
      AND b.days_coverage < b.target_min_days
      AND b.has_zero_stock_flag = 0
)
SELECT * FROM stock_zero_alerts
UNION ALL
SELECT * FROM obsolete_alerts
UNION ALL
SELECT * FROM overstock_alerts
UNION ALL
SELECT * FROM understock_alerts;
GO

------------------------------------------------------------------
-- 7.7 gold.vw_action_recommendation_priority
--     Acciones ordenadas por impacto x urgencia.
--     priority_score = impact * severity_weight
--     severity_weight: HIGH=3, MEDIUM=2, LOW=1.
--     priority_rank: ranking dentro de cada tenant (1 = mas urgente).
------------------------------------------------------------------
IF OBJECT_ID('gold.vw_action_recommendation_priority','V') IS NOT NULL DROP VIEW gold.vw_action_recommendation_priority;
GO
CREATE VIEW gold.vw_action_recommendation_priority AS
WITH scored AS (
    SELECT
        a.*,
        CASE a.severity WHEN N'HIGH' THEN 3 WHEN N'MEDIUM' THEN 2 ELSE 1 END AS severity_weight,
        CAST(ISNULL(a.estimated_impact_usd, 0) *
             CASE a.severity WHEN N'HIGH' THEN 3 WHEN N'MEDIUM' THEN 2 ELSE 1 END
             AS DECIMAL(18,4))                                                AS priority_score
    FROM gold.vw_active_alerts a
)
SELECT
    s.alert_id, s.tenant_id, s.iso_year_week, s.[level],
    s.store_id, s.sku_id, s.brand_id,
    s.sku_code, s.sku_name, s.brand_name, s.store_name,
    s.alert_type, s.severity, s.metric_value, s.threshold,
    s.suggested_action, s.estimated_impact_usd,
    s.severity_weight, s.priority_score,
    ROW_NUMBER() OVER (
        PARTITION BY s.tenant_id
        ORDER BY s.priority_score DESC, s.alert_id   -- tiebreaker determinista
    ) AS priority_rank
FROM scored s;
GO
