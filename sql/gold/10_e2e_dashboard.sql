USE pymeconta_local;
SET NOCOUNT ON;
GO

DECLARE @tenant_id BIGINT       = 7;
DECLARE @t0        DATETIME2(3) = SYSUTCDATETIME();
DECLARE @t_step    DATETIME2(3);
DECLARE @ms        INT;
DECLARE @msg       NVARCHAR(400);

RAISERROR(N'================================================================', 10, 1) WITH NOWAIT;
SET @msg = CONCAT(N'  GOLD PIPELINE END-TO-END  -  tenant=', @tenant_id,
                  N'  -  inicio ', CONVERT(NVARCHAR(30), @t0, 121));
RAISERROR(@msg, 10, 1) WITH NOWAIT;
RAISERROR(N'================================================================', 10, 1) WITH NOWAIT;

IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = N'gold')
BEGIN
    RAISERROR(N'ERROR: schema [gold] no existe. Ejecutar Bloque 1 primero.', 16, 1);
    RETURN;
END;
IF OBJECT_ID(N'gold.dim_date',N'U') IS NULL OR
   OBJECT_ID(N'gold.etl_batch_log',N'U') IS NULL OR
   OBJECT_ID(N'gold.sp_refresh_all',N'P') IS NULL OR
   OBJECT_ID(N'gold.sp_run_validations',N'P') IS NULL
BEGIN
    RAISERROR(N'ERROR: objetos prerrequisito faltan. Ejecutar Bloques 1-9.', 16, 1);
    RETURN;
END;
RAISERROR(N'STEP 0: pre-requisitos OK', 10, 1) WITH NOWAIT;

SET @t_step = SYSUTCDATETIME();
RAISERROR(N'STEP 1: seedings...', 10, 1) WITH NOWAIT;
IF @tenant_id = 7
BEGIN
    EXEC gold.sp_seed_brand_mapping_emp7;
    EXEC gold.sp_seed_store_classification_emp7;
    EXEC gold.sp_seed_business_rules_emp7;
    EXEC gold.sp_seed_society_mapping_emp7;
END;
SET @ms = DATEDIFF(MILLISECOND, @t_step, SYSUTCDATETIME());
SET @msg = CONCAT(N'         seedings OK (', @ms, N' ms)');
RAISERROR(@msg, 10, 1) WITH NOWAIT;

SET @t_step = SYSUTCDATETIME();
RAISERROR(N'STEP 2: sp_refresh_all...', 10, 1) WITH NOWAIT;
DECLARE @bid UNIQUEIDENTIFIER;
EXEC gold.sp_refresh_all @tenant_id = @tenant_id, @batch_id = @bid OUTPUT;
SET @ms = DATEDIFF(MILLISECOND, @t_step, SYSUTCDATETIME());
SET @msg = CONCAT(N'         refresh OK (', @ms, N' ms) batch=', CAST(@bid AS NVARCHAR(36)));
RAISERROR(@msg, 10, 1) WITH NOWAIT;

SET @t_step = SYSUTCDATETIME();
RAISERROR(N'STEP 3: validaciones...', 10, 1) WITH NOWAIT;
EXEC gold.sp_run_validations @tenant_id = @tenant_id;
SET @ms = DATEDIFF(MILLISECOND, @t_step, SYSUTCDATETIME());
SET @msg = CONCAT(N'         validaciones OK (', @ms, N' ms) -- ver Result Set 1');
RAISERROR(@msg, 10, 1) WITH NOWAIT;

RAISERROR(N'STEP 4: dashboard (6 grids)', 10, 1) WITH NOWAIT;

SELECT N'4.1 INVENTARIO DIMENSIONAL' AS seccion, *
  FROM (
    SELECT
        (SELECT COUNT(*) FROM gold.dim_sku       WHERE tenant_id=@tenant_id AND is_active=1) AS skus_activos,
        (SELECT COUNT(*) FROM gold.dim_store     WHERE tenant_id=@tenant_id AND is_active=1) AS tiendas_activas,
        (SELECT COUNT(*) FROM gold.dim_category  WHERE tenant_id=@tenant_id AND is_active=1) AS categorias,
        (SELECT COUNT(DISTINCT brand_id) FROM gold.dim_sku WHERE tenant_id=@tenant_id AND is_active=1) AS marcas,
        (SELECT COUNT(*) FROM gold.fact_sales_weekly      WHERE tenant_id=@tenant_id) AS fact_sales_rows,
        (SELECT COUNT(*) FROM gold.fact_stock_weekly      WHERE tenant_id=@tenant_id) AS fact_stock_rows,
        (SELECT COUNT(*) FROM gold.fact_stock_movements   WHERE tenant_id=@tenant_id) AS fact_mov_rows,
        (SELECT COUNT(*) FROM gold.fact_transfers         WHERE tenant_id=@tenant_id) AS fact_transfer_rows,
        (SELECT COUNT(*) FROM gold.fact_sales_plan        WHERE tenant_id=@tenant_id) AS fact_plan_rows
  ) x;

;WITH lw AS (SELECT MAX(iso_year_week) AS w FROM gold.fact_sales_weekly WHERE tenant_id=@tenant_id)
SELECT
    N'4.2 VENTAS ULTIMA SEMANA' AS seccion,
    lw.w                                              AS week_id,
    CAST(SUM(units_sold_net) AS DECIMAL(18,2))        AS units_sold_net,
    CAST(SUM(revenue_net)    AS DECIMAL(18,2))        AS revenue_net,
    CAST(SUM(cogs)           AS DECIMAL(18,2))        AS cogs,
    CAST(SUM(gross_margin)   AS DECIMAL(18,2))        AS gross_margin,
    CASE WHEN SUM(revenue_net) > 0
         THEN CAST(SUM(gross_margin)/SUM(revenue_net) AS DECIMAL(9,4))
         ELSE NULL END                                AS margin_pct
FROM gold.fact_sales_weekly f, lw
WHERE f.tenant_id = @tenant_id AND f.iso_year_week = lw.w
GROUP BY lw.w;

SELECT N'4.3 STORE DASHBOARD' AS seccion, store_id, store_name, block_AB,
       units_sold, revenue, gross_margin, gross_margin_pct, tickets, avg_ticket,
       stock_units, skus_zero_stock, skus_obsolete
  FROM gold.vw_store_dashboard
 WHERE tenant_id = @tenant_id
 ORDER BY revenue DESC, store_id;

SELECT N'4.4 BRAND PERFORMANCE' AS seccion, brand_name,
       units_sold, revenue, planned_units, planned_revenue,
       units_vs_plan_pct, revenue_vs_plan_pct,
       stock_units, skus_count, skus_zero_stock
  FROM gold.vw_brand_performance
 WHERE tenant_id = @tenant_id
 ORDER BY revenue DESC, brand_id;

;WITH lw AS (SELECT MAX(iso_year_week) AS w FROM gold.fact_stock_weekly WHERE tenant_id=@tenant_id)
SELECT
    N'4.5 STOCK FIN SEMANA' AS seccion,
    lw.w                                                  AS week_id,
    f.store_id,
    COUNT(*)                                              AS pares_sku_store,
    CAST(SUM(f.stock_units) AS DECIMAL(18,2))             AS stock_units,
    CAST(SUM(f.stock_value) AS DECIMAL(18,2))             AS stock_value,
    SUM(CAST(f.has_zero_stock_flag AS INT))               AS skus_zero,
    SUM(CAST(f.is_obsolete_flag    AS INT))               AS skus_obsoletos
FROM gold.fact_stock_weekly f, lw
WHERE f.tenant_id = @tenant_id AND f.iso_year_week = lw.w
GROUP BY lw.w, f.store_id
ORDER BY stock_value DESC;

SELECT N'4.6 ALERTAS ACTIVAS' AS seccion,
       alert_type, severity, COUNT(*) AS alertas,
       CAST(SUM(estimated_impact_usd) AS DECIMAL(18,2)) AS impacto_total
  FROM gold.vw_active_alerts
 WHERE tenant_id = @tenant_id
 GROUP BY alert_type, severity
 ORDER BY impacto_total DESC;

SELECT N'4.7 DQ METRICS (batch actual)' AS seccion,
       table_name, metric_name, CAST(metric_value AS INT) AS value, severity
  FROM gold.etl_data_quality_metrics
 WHERE tenant_id = @tenant_id AND batch_id = @bid
 ORDER BY severity DESC, table_name, metric_name;

SET @ms = DATEDIFF(MILLISECOND, @t0, SYSUTCDATETIME());
RAISERROR(N'================================================================', 10, 1) WITH NOWAIT;
SET @msg = CONCAT(N'  PIPELINE COMPLETO en ', @ms, N' ms  -  batch=', CAST(@bid AS NVARCHAR(36)));
RAISERROR(@msg, 10, 1) WITH NOWAIT;
RAISERROR(N'================================================================', 10, 1) WITH NOWAIT;
GO
