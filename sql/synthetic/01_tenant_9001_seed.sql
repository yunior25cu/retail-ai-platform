/* ============================================================
 * sql/synthetic/01_tenant_9001_seed.sql
 * Purpose  : Synthetic retail data for tenant_id = 9001.
 *            Used by the eval framework and local development.
 *
 * Tenant profile (RetailDemo SA — Uruguay):
 *   Brands  : URBAN PRO (1)  · SPORT ELITE (2)  · BASE LINE (3)
 *   Stores  : T01-T04 retail + T05 depósito (store_id 101-105)
 *   SKUs    : 200  (80 + 60 + 60 por marca)
 *   Weeks   : últimas 52 ISO-semanas desde la fecha de ejecución
 *   Moneda  : UYU
 *
 * Alert scenarios generated (for vw_active_alerts):
 *   OVERSTOCK  sku  1-10  — URBAN PRO fast, exceso de stock
 *   UNDERSTOCK sku 11-20  — URBAN PRO fast, stock crítico
 *   OBSOLETE   sku141-155 — BASE LINE sin ventas >120 días
 *   STOCK_ZERO sku181-200 — BASE LINE quiebre total (store 101)
 *   GREEN      resto       — cobertura normal
 *
 * ABCD velocity (vw_sku_velocity_segmented):
 *   A: sku  1-50   B: sku  51-100
 *   C: sku101-150  D: sku 151-200
 *
 * Tickets  : siempre 0 (no hay dbo.documento para este tenant).
 *
 * Idempotente : DELETE WHERE tenant_id=9001 + INSERT.
 * Prerequisito: gold schema (01-11_*.sql) + dim_date poblado.
 * ============================================================ */

SET NOCOUNT ON;
GO

DECLARE @tenant  BIGINT           = 9001;
DECLARE @batch   UNIQUEIDENTIFIER = NEWID();
DECLARE @today   DATE             = CAST(SYSUTCDATETIME() AS DATE);
DECLARE @ccy     NVARCHAR(3)      = N'UYU';

/* ── Verificar dim_date ───────────────────────────────────────────────────── */
IF NOT EXISTS (SELECT 1 FROM gold.dim_date WHERE [date] = @today)
BEGIN
    RAISERROR(N'dim_date no contiene la fecha de hoy. Ejecutar 02_dim_date.sql primero.', 16, 1);
    RETURN;
END;

/* ── DELETE idempotente ───────────────────────────────────────────────────── */
DELETE FROM gold.fact_sales_plan    WHERE tenant_id = @tenant;
DELETE FROM gold.fact_stock_weekly  WHERE tenant_id = @tenant;
DELETE FROM gold.fact_sales_weekly  WHERE tenant_id = @tenant;
DELETE FROM gold.dim_business_rules WHERE tenant_id = @tenant;
DELETE FROM gold.dim_sku            WHERE tenant_id = @tenant;
DELETE FROM gold.dim_store          WHERE tenant_id = @tenant;
DELETE FROM gold.dim_category       WHERE tenant_id = @tenant;

PRINT CONCAT(N'[9001] Datos existentes eliminados. batch=', CAST(@batch AS NVARCHAR(40)));

/* ═══════════════════════════════════════════════════════════════════════════
   PARTE 1 — Dimensiones
   ═══════════════════════════════════════════════════════════════════════════ */

/* ── dim_category ─────────────────────────────────────────────────────────── */
INSERT INTO gold.dim_category
    (tenant_id, category_id, category_code, category_name,
     parent_category_id, category_level, is_active, etl_batch_id)
VALUES
    (@tenant, 1, N'ROPA',  N'Ropa',       NULL, 1, 1, @batch),
    (@tenant, 2, N'CALZ',  N'Calzado',    NULL, 1, 1, @batch),
    (@tenant, 3, N'ACCES', N'Accesorios', NULL, 1, 1, @batch);

PRINT CONCAT(N'[9001] dim_category: ', @@ROWCOUNT, N' filas');

/* ── dim_store (4 retail + 1 depósito) ───────────────────────────────────── */
INSERT INTO gold.dim_store
    (tenant_id, store_id, store_code, store_name,
     is_main, is_store_flag, block_AB, region, society_id, is_active, etl_batch_id)
VALUES
    (@tenant, 101, N'T01', N'Sucursal Centro',    1, 1, N'A', N'Montevideo', 1, 1, @batch),
    (@tenant, 102, N'T02', N'Sucursal Pocitos',   0, 1, N'A', N'Montevideo', 1, 1, @batch),
    (@tenant, 103, N'T03', N'Sucursal Punta',     0, 1, N'B', N'Maldonado',  1, 1, @batch),
    (@tenant, 104, N'T04', N'Sucursal Canelones', 0, 1, N'B', N'Canelones',  1, 1, @batch),
    (@tenant, 105, N'T05', N'Depósito Central',   0, 0, N'NO CLASIFICADO', N'Montevideo', 1, 1, @batch);

PRINT CONCAT(N'[9001] dim_store: ', @@ROWCOUNT, N' filas');

/* ── dim_sku (200 SKUs) ───────────────────────────────────────────────────── *
 *  sku_id  1- 80: URBAN PRO   (brand_id=1) — Ropa/Calzado alternado
 *  sku_id 81-140: SPORT ELITE (brand_id=2) — Calzado/Accesorios alternado
 *  sku_id141-200: BASE LINE   (brand_id=3) — Ropa/Accesorios alternado
 * ──────────────────────────────────────────────────────────────────────────*/
;WITH nums AS (SELECT 1 AS n UNION ALL SELECT n + 1 FROM nums WHERE n < 200)
INSERT INTO gold.dim_sku (
    tenant_id, sku_id, sku_code, sku_barcode, sku_name,
    is_service, category_id, brand_id, brand_name,
    season_id, season_name, list_price, is_active, etl_batch_id
)
SELECT
    @tenant,
    n,
    CONCAT(N'SKU-', RIGHT(CONCAT(N'0000', n), 4)),
    CONCAT(N'77', RIGHT(CONCAT(N'000000000', CAST(n * 13 AS NVARCHAR(20))), 8)),
    CONCAT(
        b.brand_prefix,
        CASE c.category_id WHEN 1 THEN N'Remera ' WHEN 2 THEN N'Zapatilla ' ELSE N'Mochila ' END,
        CAST(n AS NVARCHAR(10))
    ),
    0,                  -- is_service
    c.category_id,
    b.brand_id,
    b.brand_name,
    0, N'SIN TEMPORADA',
    /* list_price en UYU — decreciente por rango */
    CAST(
        CASE
            WHEN n <=  20 THEN 2800 + (n * 73)  % 1200   -- fast: 2800-4000
            WHEN n <=  80 THEN 1200 + (n * 37)  % 800    -- mid:  1200-2000
            WHEN n <= 140 THEN 1500 + (n * 29)  % 600    -- sport: 1500-2100
            ELSE               600  + (n * 17)  % 400    -- base:  600-1000
        END AS DECIMAL(18,4)
    ),
    1, @batch
FROM nums
CROSS APPLY (SELECT
    CASE WHEN n <=  80 THEN 1   WHEN n <= 140 THEN 2   ELSE 3   END AS brand_id,
    CASE WHEN n <=  80 THEN N'URBAN PRO '
         WHEN n <= 140 THEN N'SPORT ELITE '
         ELSE               N'BASE LINE '  END AS brand_name,
    CASE WHEN n <=  80 THEN N'Urban Pro '
         WHEN n <= 140 THEN N'Sport Elite '
         ELSE               N'Base Line '  END AS brand_prefix
) b
CROSS APPLY (SELECT
    CASE
        WHEN n <=  80 THEN CASE WHEN n % 2 = 1 THEN 1 ELSE 2 END  -- Ropa/Calzado
        WHEN n <= 140 THEN CASE WHEN n % 2 = 1 THEN 2 ELSE 3 END  -- Calzado/Accesorios
        ELSE               CASE WHEN n % 2 = 1 THEN 1 ELSE 3 END  -- Ropa/Accesorios
    END AS category_id
) c
OPTION (MAXRECURSION 200);

PRINT CONCAT(N'[9001] dim_sku: ', @@ROWCOUNT, N' filas');

/* ── dim_business_rules ───────────────────────────────────────────────────── */
INSERT INTO gold.dim_business_rules
    (tenant_id, brand_id, category_id,
     coverage_min_days, coverage_max_days, days_no_sale_obsolete,
     primary_action, discount_pct, priority, is_active)
VALUES
    (@tenant, 0, 0, 30,  90,  84, N'REPONER',  NULL,  100, 1),  -- genérico
    (@tenant, 1, 0, 21,  75,  60, N'REPONER',  NULL,   10, 1),  -- URBAN PRO
    (@tenant, 2, 0, 28,  90,  84, N'REPONER',  NULL,   10, 1),  -- SPORT ELITE
    (@tenant, 3, 0, 14,  60, 100, N'LIQUIDAR', 15.00,  10, 1);  -- BASE LINE

PRINT CONCAT(N'[9001] dim_business_rules: ', @@ROWCOUNT, N' filas');

/* ═══════════════════════════════════════════════════════════════════════════
   PARTE 2 — fact_sales_weekly (últimas 52 semanas ISO)
   ═══════════════════════════════════════════════════════════════════════════
   Reglas de presencia (store_id, sku_id):
     sku  1-20  (fast A): stores 101-104, todas las semanas
     sku 21-80  (mid  B): stores 101+102, ~80% semanas (CHECKSUM)
     sku 81-140 (sport ): stores 102+103, ~70% semanas
     sku141-155 (obsolete): stores 103+104, solo semanas >120d atrás
     sku156-180 (slow  ): stores 103+104, ~50% semanas
     sku181-190 (zero-H): store 101, ~40% semanas (incluso recientes)
     sku191-200 (zero-M): store 101, ~30% semanas, solo >56d atrás
   ════════════════════════════════════════════════════════════════════════════ */
;WITH
weeks AS (
    SELECT TOP 52 iso_year_week, [date] AS week_end_date
    FROM gold.dim_date
    WHERE day_of_week = 7 AND [date] <= @today
    ORDER BY [date] DESC
),
candidates AS (
    SELECT w.iso_year_week, w.week_end_date, s.store_id, sk.sku_id
    FROM weeks w
    CROSS JOIN (VALUES (101),(102),(103),(104)) s(store_id)
    CROSS JOIN (
        SELECT sku_id FROM gold.dim_sku WHERE tenant_id = @tenant AND is_active = 1
    ) sk
    WHERE
        /* URBAN PRO fast (1-20): todas las tiendas retail, todas las semanas */
        (sk.sku_id BETWEEN   1 AND  20  AND s.store_id IN (101,102,103,104))
        /* URBAN PRO mid (21-80): tiendas 101+102, 80% semanas */
     OR (sk.sku_id BETWEEN  21 AND  80  AND s.store_id IN (101,102)
         AND ABS(CAST(CHECKSUM(sk.sku_id, w.iso_year_week, s.store_id) AS BIGINT)) % 10 <= 7)
        /* SPORT ELITE (81-140): tiendas 102+103, 70% semanas */
     OR (sk.sku_id BETWEEN  81 AND 140  AND s.store_id IN (102,103)
         AND ABS(CAST(CHECKSUM(sk.sku_id, w.iso_year_week, s.store_id) AS BIGINT)) % 10 <= 6)
        /* OBSOLETE (141-155): tiendas 103+104, solo >120 días atrás */
     OR (sk.sku_id BETWEEN 141 AND 155  AND s.store_id IN (103,104)
         AND w.week_end_date < DATEADD(DAY, -120, @today)
         AND ABS(CAST(CHECKSUM(sk.sku_id, w.iso_year_week) AS BIGINT)) % 10 <= 4)
        /* BASE LINE lento (156-180): tiendas 103+104, 50% semanas */
     OR (sk.sku_id BETWEEN 156 AND 180  AND s.store_id IN (103,104)
         AND ABS(CAST(CHECKSUM(sk.sku_id, w.iso_year_week, s.store_id) AS BIGINT)) % 10 <= 4)
        /* ZERO STOCK HIGH (181-190): tienda 101, ~40% semanas incluso recientes */
     OR (sk.sku_id BETWEEN 181 AND 190  AND s.store_id = 101
         AND ABS(CAST(CHECKSUM(sk.sku_id, w.iso_year_week) AS BIGINT)) % 10 <= 3)
        /* ZERO STOCK MEDIUM (191-200): tienda 101, solo >56 días atrás */
     OR (sk.sku_id BETWEEN 191 AND 200  AND s.store_id = 101
         AND w.week_end_date < DATEADD(DAY, -56, @today)
         AND ABS(CAST(CHECKSUM(sk.sku_id, w.iso_year_week) AS BIGINT)) % 10 <= 2)
)
INSERT INTO gold.fact_sales_weekly (
    tenant_id, iso_year_week, store_id, sku_id, brand_id, category_id,
    units_sold_gross, units_returned, units_sold_net,
    revenue_gross, revenue_returned, revenue_net,
    cogs, gross_margin, gross_margin_pct,
    tickets, avg_ticket, discount_amount, currency_code, etl_batch_id
)
SELECT
    @tenant,
    c.iso_year_week,
    c.store_id,
    c.sku_id,
    ds.brand_id,
    ds.category_id,
    v.u_gross,
    CAST(v.u_gross * 0.02 AS DECIMAL(18,4)),
    CAST(v.u_gross * 0.98 AS DECIMAL(18,4)),
    CAST(v.u_gross * ds.list_price            AS DECIMAL(18,4)),
    CAST(v.u_gross * ds.list_price * 0.02     AS DECIMAL(18,4)),
    CAST(v.u_gross * ds.list_price * 0.98     AS DECIMAL(18,4)),
    CAST(v.u_gross * ds.list_price * 0.98 * 0.55 AS DECIMAL(18,4)),
    CAST(v.u_gross * ds.list_price * 0.98 * 0.45 AS DECIMAL(18,4)),
    CAST(0.4500 AS DECIMAL(9,4)),
    CAST(CEILING(v.u_gross / 2.0) AS INT),  -- tickets semi-aditivo aproximado
    CAST(ds.list_price * 2.0 AS DECIMAL(18,4)),
    CAST(0 AS DECIMAL(18,4)),
    @ccy,
    @batch
FROM candidates c
JOIN gold.dim_sku ds ON ds.tenant_id = @tenant AND ds.sku_id = c.sku_id
CROSS APPLY (
    SELECT CAST(
        CASE
            WHEN c.sku_id BETWEEN   1 AND  20 THEN 8 + ABS(CHECKSUM(c.sku_id, c.iso_year_week, c.store_id)) % 6  -- 8-13 u/sem
            WHEN c.sku_id BETWEEN  21 AND  80 THEN 3 + ABS(CHECKSUM(c.sku_id, c.iso_year_week, c.store_id)) % 4  -- 3-6
            WHEN c.sku_id BETWEEN  81 AND 140 THEN 2 + ABS(CHECKSUM(c.sku_id, c.iso_year_week, c.store_id)) % 3  -- 2-4
            WHEN c.sku_id BETWEEN 141 AND 155 THEN 1 + ABS(CHECKSUM(c.sku_id, c.iso_year_week)) % 2              -- 1-2
            WHEN c.sku_id BETWEEN 156 AND 180 THEN 2 + ABS(CHECKSUM(c.sku_id, c.iso_year_week)) % 2              -- 2-3
            ELSE                                   1 + ABS(CHECKSUM(c.sku_id, c.iso_year_week)) % 2              -- 1-2
        END AS DECIMAL(18,4)
    ) AS u_gross
) v;

PRINT CONCAT(N'[9001] fact_sales_weekly: ', @@ROWCOUNT, N' filas');

/* ═══════════════════════════════════════════════════════════════════════════
   PARTE 3 — fact_stock_weekly (últimas 4 semanas)
   ═══════════════════════════════════════════════════════════════════════════
   Combinaciones (sku_id, store_id) presentes:
     sku  1-140 : las 5 tiendas
     sku141-155 : solo tiendas 103+104  (obsoleto, con stock inmovilizado)
     sku156-180 : las 5 tiendas
     sku181-200 : solo tienda 101       (quiebre, stock=0)
   ════════════════════════════════════════════════════════════════════════════ */
;WITH
last4w AS (
    SELECT TOP 4 iso_year_week
    FROM gold.dim_date WHERE day_of_week = 7 AND [date] <= @today
    ORDER BY [date] DESC
),
sku_store AS (
    SELECT ds.sku_id, ds.brand_id, ds.list_price, s.store_id
    FROM gold.dim_sku ds
    CROSS JOIN (VALUES (101),(102),(103),(104),(105)) s(store_id)
    WHERE ds.tenant_id = @tenant AND ds.is_active = 1
      /* obsoleto sólo en tiendas donde tenía presencia */
      AND NOT (ds.sku_id BETWEEN 141 AND 155 AND s.store_id NOT IN (103,104))
      /* quiebre sólo en tienda 101 */
      AND NOT (ds.sku_id BETWEEN 181 AND 200 AND s.store_id <> 101)
)
INSERT INTO gold.fact_stock_weekly (
    tenant_id, iso_year_week, store_id, sku_id,
    stock_units, stock_value, unit_cost,
    stock_min, stock_max,
    has_zero_stock_flag, is_obsolete_flag,
    days_since_last_sale, days_since_last_movement,
    last_sale_date, last_movement_date,
    currency_code, etl_batch_id
)
SELECT
    @tenant,
    w.iso_year_week,
    ss.store_id,
    ss.sku_id,
    sc.stock_units,
    CAST(sc.stock_units * sc.unit_cost AS DECIMAL(18,4)),
    sc.unit_cost,
    NULL, NULL,
    CASE WHEN sc.stock_units = 0 THEN 1 ELSE 0 END,
    /* is_obsolete: solo sku 141-155 en tiendas 103+104 */
    CASE WHEN ss.sku_id BETWEEN 141 AND 155 AND ss.store_id IN (103,104) THEN 1 ELSE 0 END,
    /* days_since_last_sale */
    CASE
        WHEN ss.sku_id BETWEEN 141 AND 155 THEN 125
        WHEN ss.sku_id BETWEEN 181 AND 200 THEN 3
        WHEN ss.sku_id BETWEEN   1 AND  20 THEN 3
        ELSE 7
    END,
    7,  -- days_since_last_movement
    DATEADD(DAY,
        -CASE
            WHEN ss.sku_id BETWEEN 141 AND 155 THEN 125
            WHEN ss.sku_id BETWEEN 181 AND 200 THEN 3
            WHEN ss.sku_id BETWEEN   1 AND  20 THEN 3
            ELSE 7
        END, @today),
    DATEADD(DAY, -7, @today),
    @ccy,
    @batch
FROM last4w w
CROSS JOIN sku_store ss
CROSS APPLY (
    SELECT
        CAST(ss.list_price * 0.55 AS DECIMAL(18,4)) AS unit_cost,
        CAST(
            CASE
                /* OVERSTOCK: exceso claro (180-240u → days_coverage ~120-160) */
                WHEN ss.sku_id BETWEEN   1 AND  10 THEN 180 + ABS(CHECKSUM(ss.sku_id, ss.store_id)) % 60
                /* UNDERSTOCK: crítico (5-15u → days_coverage ~3-10) */
                WHEN ss.sku_id BETWEEN  11 AND  20 THEN 5   + ABS(CHECKSUM(ss.sku_id, ss.store_id)) % 10
                /* ZERO STOCK */
                WHEN ss.sku_id BETWEEN 181 AND 200 THEN 0
                /* OBSOLETE: stock inmovilizado sin rotación */
                WHEN ss.sku_id BETWEEN 141 AND 155 THEN 30  + ABS(CHECKSUM(ss.sku_id, ss.store_id)) % 20
                /* URBAN PRO mid: stock equilibrado (20-45u → cov 32-71d) */
                WHEN ss.sku_id BETWEEN  21 AND  80 THEN 20  + ABS(CAST(CHECKSUM(ss.sku_id, ss.store_id) AS BIGINT)) % 25
                /* SPORT ELITE: stock normal (18-48u → cov 43-114d en rango SPORT) */
                WHEN ss.sku_id BETWEEN  81 AND 140 THEN 18  + ABS(CAST(CHECKSUM(ss.sku_id, ss.store_id) AS BIGINT)) % 30
                /* BASE LINE lento: stock mínimo (5-15u → cov 25-70d) */
                ELSE                                     5  + ABS(CAST(CHECKSUM(ss.sku_id, ss.store_id) AS BIGINT)) % 10
            END AS DECIMAL(18,4)
        ) AS stock_units
) sc;

PRINT CONCAT(N'[9001] fact_stock_weekly: ', @@ROWCOUNT, N' filas');

/* ═══════════════════════════════════════════════════════════════════════════
   PARTE 4 — fact_sales_plan (52 semanas × 3 marcas, agregado por tienda)
   ═══════════════════════════════════════════════════════════════════════════
   Plan ligeramente por encima del real (≈+4%) para generar métricas
   revenue_vs_plan_pct < 1.0 y contexto para preguntas de análisis.
   ════════════════════════════════════════════════════════════════════════════ */
;WITH
weeks AS (
    SELECT TOP 52 iso_year_week
    FROM gold.dim_date WHERE day_of_week = 7 AND [date] <= @today
    ORDER BY [date] DESC
)
INSERT INTO gold.fact_sales_plan
    (tenant_id, iso_year_week, brand_id, store_id, plan_version,
     planned_units, planned_revenue, currency_code)
SELECT
    @tenant,
    w.iso_year_week,
    b.brand_id,
    0,          -- store_id=0 = agregado todas las tiendas
    N'v1-synthetic',
    b.planned_units,
    b.planned_revenue,
    @ccy
FROM weeks w
CROSS JOIN (VALUES
    /* brand_id, planned_units/sem, planned_revenue/sem (UYU) */
    (1, CAST(1400.0 AS DECIMAL(18,4)), CAST(3350000.0 AS DECIMAL(18,4))),  -- URBAN PRO
    (2, CAST( 420.0 AS DECIMAL(18,4)), CAST( 730000.0 AS DECIMAL(18,4))),  -- SPORT ELITE
    (3, CAST( 210.0 AS DECIMAL(18,4)), CAST( 160000.0 AS DECIMAL(18,4)))   -- BASE LINE
) b(brand_id, planned_units, planned_revenue);

PRINT CONCAT(N'[9001] fact_sales_plan: ', @@ROWCOUNT, N' filas');

/* ── Resumen final ─────────────────────────────────────────────────────────── */
PRINT N'';
PRINT N'═══════════════════════════════════════════════════════════';
PRINT CONCAT(N'Tenant 9001 sembrado. batch = ', CAST(@batch AS NVARCHAR(40)));
PRINT N'Vistas que deben funcionar después de ejecutar este script:';
PRINT N'  gold.vw_store_dashboard            (tickets=0, resto OK)';
PRINT N'  gold.vw_brand_performance          (incluye vs-plan %)';
PRINT N'  gold.vw_sku_coverage_status        (RED/YELLOW/GREEN/GREY)';
PRINT N'  gold.vw_sku_velocity_segmented     (A/B/C/D)';
PRINT N'  gold.vw_active_alerts              (OVERSTOCK/UNDERSTOCK/OBSOLETE/STOCK_ZERO)';
PRINT N'  gold.vw_action_recommendation_priority';
PRINT N'═══════════════════════════════════════════════════════════';
GO
