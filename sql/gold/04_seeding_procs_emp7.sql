/* ============================================================
 * 04_seeding_procs_emp7.sql  (originally: block_4)
 * Purpose : tenant-specific seeding for the POC tenant (id=7).
 *           For other tenants, copy these procs and adjust the tenant id
 *           + heuristics. Production scenarios should replace these with
 *           an admin UI that writes to the enrichment tables.
 * Depends : 03_enrichment_tables.sql, 05_dimensions_refresh.sql
 *           (sp_seed_sales_plan_emp7 needs dim_sku populated).
 * Frequency: on-demand. All procs are idempotent (DELETE+INSERT per tenant).
 *
 * Note on producto.codigo duplicates:
 *   The source ERP allows duplicate codigo within id_empresa. The brand
 *   seeding dedupes by code, keeping the most recent active product to
 *   prevent PK violations on dim_brand_mapping.
 * ============================================================ */

------------------------------------------------------------------
-- sp_seed_brand_mapping_emp7 : assign brand by sku_code prefix
------------------------------------------------------------------
IF OBJECT_ID('gold.sp_seed_brand_mapping_emp7','P') IS NOT NULL DROP PROCEDURE gold.sp_seed_brand_mapping_emp7;
GO
CREATE PROCEDURE gold.sp_seed_brand_mapping_emp7
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @tenant BIGINT = 7;

    DELETE FROM gold.dim_brand_mapping WHERE tenant_id = @tenant;

    -- Dedup by sku_code (source allows duplicates); keep the most recently
    -- updated active product per code.
    ;WITH ranked AS (
        SELECT p.id, p.codigo, p.es_servicio,
               ROW_NUMBER() OVER (
                   PARTITION BY p.codigo
                   ORDER BY p.updated_at DESC, p.id DESC
               ) AS rn
        FROM dbo.producto p
        WHERE p.id_empresa = @tenant AND p.[delete] = 0
    )
    INSERT INTO gold.dim_brand_mapping (tenant_id, sku_code, brand_id, brand_name, business_type)
    SELECT
        @tenant,
        r.codigo,
        CASE
            WHEN r.codigo LIKE N'AT%' THEN 1
            WHEN r.codigo LIKE N'IB%' THEN 2
            ELSE 3
        END AS brand_id,
        CASE
            WHEN r.codigo LIKE N'AT%' THEN N'PRO BRAND'
            WHEN r.codigo LIKE N'IB%' THEN N'RECOVERY BRAND'
            ELSE N'ESSENTIAL'
        END AS brand_name,
        CASE WHEN r.es_servicio = 1 THEN N'SERVICE' ELSE N'RETAIL' END
    FROM ranked r
    WHERE r.rn = 1;

    DECLARE @inserted INT = @@ROWCOUNT;
    DECLARE @duplicates INT = (
        SELECT COUNT(*) FROM dbo.producto
         WHERE id_empresa = @tenant AND [delete] = 0
         GROUP BY codigo HAVING COUNT(*) > 1
    );
    IF @duplicates > 0
        PRINT CONCAT(N'WARNING: ', @duplicates,
                     N' duplicate sku codes in producto. Kept most-recent active per code.');
    PRINT CONCAT(N'sp_seed_brand_mapping_emp7: ', @inserted, N' rows');
END;
GO

------------------------------------------------------------------
-- sp_seed_store_classification_emp7 : heuristic by warehouse name
-- (POC: tenant has only 4 B2B warehouses; rules are synthetic.)
------------------------------------------------------------------
IF OBJECT_ID('gold.sp_seed_store_classification_emp7','P') IS NOT NULL DROP PROCEDURE gold.sp_seed_store_classification_emp7;
GO
CREATE PROCEDURE gold.sp_seed_store_classification_emp7
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @tenant BIGINT = 7;

    DELETE FROM gold.dim_store_classification WHERE tenant_id = @tenant;

    INSERT INTO gold.dim_store_classification (tenant_id, store_id, is_store_flag, block_AB, region)
    SELECT
        @tenant,
        a.id,
        CASE
            WHEN a.denominacion LIKE N'%Convenios%' OR a.denominacion LIKE N'%Marketing%' THEN 1
            ELSE 0
        END AS is_store_flag,
        CASE WHEN a.principal = 1 THEN N'A' ELSE N'B' END AS block_AB,
        N'Montevideo' AS region
    FROM dbo.almacen a
    WHERE a.id_empresa = @tenant AND a.[delete] = 0;

    PRINT CONCAT(N'sp_seed_store_classification_emp7: ', CAST(@@ROWCOUNT AS NVARCHAR(20)), N' rows');
END;
GO

------------------------------------------------------------------
-- sp_seed_business_rules_emp7 : 4 POC rules
------------------------------------------------------------------
IF OBJECT_ID('gold.sp_seed_business_rules_emp7','P') IS NOT NULL DROP PROCEDURE gold.sp_seed_business_rules_emp7;
GO
CREATE PROCEDURE gold.sp_seed_business_rules_emp7
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @tenant BIGINT = 7;

    DELETE FROM gold.dim_business_rules WHERE tenant_id = @tenant;

    INSERT INTO gold.dim_business_rules
        (tenant_id, brand_id, category_id, season_month, coverage_min_days, coverage_max_days,
         days_no_sale_obsolete, primary_action, discount_pct, priority, is_active)
    VALUES
        (@tenant, 1, 0, NULL, 45, 90,  60, N'REPONER',        NULL,    10, 1),
        (@tenant, 2, 0, NULL, 30, 60,  45, N'REPONER',        NULL,    10, 1),
        (@tenant, 0, 0, NULL, 60, 120, 90, N'LIQUIDAR',       30.0000, 50, 1),
        (@tenant, 0, 0, 6,    20, 45,  30, N'AJUSTAR_PRECIO', 15.0000, 30, 1);

    PRINT CONCAT(N'sp_seed_business_rules_emp7: ', CAST(@@ROWCOUNT AS NVARCHAR(20)), N' rules');
END;
GO

------------------------------------------------------------------
-- sp_seed_society_mapping_emp7 : 1:1 with empresa
------------------------------------------------------------------
IF OBJECT_ID('gold.sp_seed_society_mapping_emp7','P') IS NOT NULL DROP PROCEDURE gold.sp_seed_society_mapping_emp7;
GO
CREATE PROCEDURE gold.sp_seed_society_mapping_emp7
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @tenant BIGINT = 7;

    DELETE FROM gold.dim_society_mapping WHERE tenant_id = @tenant;

    INSERT INTO gold.dim_society_mapping (tenant_id, society_id, society_name, society_rut)
    SELECT @tenant, 1, e.nombre, e.rut
    FROM dbo.empresa e
    WHERE e.id = @tenant;

    PRINT CONCAT(N'sp_seed_society_mapping_emp7: ', CAST(@@ROWCOUNT AS NVARCHAR(20)), N' rows');
END;
GO

------------------------------------------------------------------
-- sp_seed_sales_plan_emp7 : plan = historical * 1.10 per (week, brand)
-- IMPORTANT : depends on gold.dim_brand_mapping (run sp_seed_brand_mapping first).
-- Filter estado IN (1,2) is intentional: aligned with fact_sales_weekly so
-- weeks with only draft sales (estado=1) also appear in plan.
------------------------------------------------------------------
IF OBJECT_ID('gold.sp_seed_sales_plan_emp7','P') IS NOT NULL DROP PROCEDURE gold.sp_seed_sales_plan_emp7;
GO
CREATE PROCEDURE gold.sp_seed_sales_plan_emp7
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @tenant BIGINT = 7;
    DECLARE @version NVARCHAR(20) = N'v1-baseline-x110';

    DELETE FROM gold.fact_sales_plan WHERE tenant_id = @tenant AND plan_version = @version;

    INSERT INTO gold.fact_sales_plan
        (tenant_id, iso_year_week, brand_id, store_id, plan_version,
         planned_units, planned_revenue, currency_code)
    SELECT
        @tenant,
        dd.iso_year_week,
        COALESCE(bm.brand_id, 0)                                                AS brand_id,
        0                                                                       AS store_id,
        @version                                                                AS plan_version,
        CAST(ROUND(SUM(dp.cantidad - ISNULL(dp.devuelto,0)) * 1.10, 4) AS DECIMAL(18,4)) AS planned_units,
        CAST(ROUND(SUM(dp.importe_base
                       * (1 - ISNULL(dp.devuelto,0)/NULLIF(dp.cantidad,0))
                       * d.tasa_cambio
                  ) * 1.10, 4) AS DECIMAL(18,4))                                AS planned_revenue,
        N'UYU'                                                                  AS currency_code
    FROM dbo.documento d
    JOIN dbo.documento_producto dp ON dp.id_documento = d.id
    JOIN dbo.producto p            ON p.id = dp.id_producto
    LEFT JOIN gold.dim_brand_mapping bm
           ON bm.tenant_id = d.id_empresa AND bm.sku_code = p.codigo
    JOIN gold.dim_date dd           ON dd.[date] = d.fecha_emision
    WHERE d.id_empresa    = @tenant
      AND d.[delete]      = 0
      AND d.estado        IN (1, 2)        -- aligned with fact_sales_weekly
      AND d.tipo_documento = 3              -- 3 = sales invoice
      AND dp.cantidad     > 0
    GROUP BY dd.iso_year_week, COALESCE(bm.brand_id, 0);

    PRINT CONCAT(N'sp_seed_sales_plan_emp7: ', CAST(@@ROWCOUNT AS NVARCHAR(20)), N' rows');
END;
GO
