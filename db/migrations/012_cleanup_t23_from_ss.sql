/* ============================================================
 * 012_cleanup_t23_from_ss.sql
 *
 * FASE 8 — Borra los datos del tenant 23 (DEMO RETAIL CO) de
 * SQL Server (pymeconta_local) tras haber migrado a PostgreSQL
 * (gold_t23.*).
 *
 * Pre-requisito: Fases 1-7 completas y verificadas en vivo:
 *   - 19.567 filas migradas a gold_t23.*  (010_migrate_data_t23.py)
 *   - 5 usuarios pueden loguear y disparar tools que devuelven datos
 *     desde gold_t23 (smoke test Fase 7)
 *
 * Qué se borra
 * ------------
 * - gold.* (tablas de retail con datos del tenant 23)
 * - api_audit.empresa_capability_override (id_empresa=23)
 * - api_audit.empresa_addon (si existe, id_empresa=23)
 *
 * Qué NO se borra (y por qué)
 * ---------------------------
 * - dim_date (compartida, no tenant-specific)
 * - gold.vw_*  y  gold.sp_* (usadas por el tenant 7 que sigue en SS)
 * - dbo.empresa #23 (el registro del tenant en el ERP, no es del AI)
 * - dbo.almacen_producto, dbo.documento, etc. (mundo ERP, intacto)
 *
 * Reversible
 * ----------
 * Si hay que rollback, re-ejecutar 010_migrate_data_t23.py en sentido
 * inverso copia gold_t23.* -> gold.*. (No incluido — solo en
 * emergencia.) Los datos quedan SEGUROS mientras gold_t23 exista.
 *
 * Verificación posterior abajo (DO block).
 * ============================================================ */

SET QUOTED_IDENTIFIER ON;
GO

BEGIN TRANSACTION;

DELETE FROM gold.fact_sales_plan        WHERE tenant_id = 23;
DELETE FROM gold.fact_sales_weekly      WHERE tenant_id = 23;
DELETE FROM gold.fact_stock_weekly      WHERE tenant_id = 23;
DELETE FROM gold.fact_stock_movements   WHERE tenant_id = 23;
DELETE FROM gold.fact_transfers         WHERE tenant_id = 23;
DELETE FROM gold.dim_business_rules     WHERE tenant_id = 23;
DELETE FROM gold.dim_brand_mapping      WHERE tenant_id = 23;
DELETE FROM gold.dim_season_mapping     WHERE tenant_id = 23;
DELETE FROM gold.dim_society_mapping    WHERE tenant_id = 23;
DELETE FROM gold.dim_store_classification WHERE tenant_id = 23;
DELETE FROM gold.dim_sku                WHERE tenant_id = 23;
DELETE FROM gold.dim_store              WHERE tenant_id = 23;
DELETE FROM gold.dim_category           WHERE tenant_id = 23;

-- Capability overrides del AI module (no del ERP)
IF OBJECT_ID('api_audit.empresa_capability_override','U') IS NOT NULL
    DELETE FROM api_audit.empresa_capability_override WHERE id_empresa = 23;

-- ETL logs de tenant 23 (no romper auditoría de otros tenants)
IF OBJECT_ID('gold.etl_batch_log','U') IS NOT NULL
    DELETE FROM gold.etl_batch_log WHERE tenant_id = 23;

IF OBJECT_ID('gold.etl_data_quality_metrics','U') IS NOT NULL
    DELETE FROM gold.etl_data_quality_metrics WHERE tenant_id = 23;

COMMIT TRANSACTION;
GO

-- Verificación: estos counts deben ser todos 0
SELECT 'fact_sales_weekly'  AS tabla, COUNT(*) AS cant FROM gold.fact_sales_weekly  WHERE tenant_id=23
UNION ALL SELECT 'fact_stock_weekly', COUNT(*) FROM gold.fact_stock_weekly  WHERE tenant_id=23
UNION ALL SELECT 'fact_sales_plan',   COUNT(*) FROM gold.fact_sales_plan    WHERE tenant_id=23
UNION ALL SELECT 'dim_sku',           COUNT(*) FROM gold.dim_sku            WHERE tenant_id=23
UNION ALL SELECT 'dim_store',         COUNT(*) FROM gold.dim_store          WHERE tenant_id=23
UNION ALL SELECT 'dim_category',      COUNT(*) FROM gold.dim_category       WHERE tenant_id=23
UNION ALL SELECT 'dim_business_rules',COUNT(*) FROM gold.dim_business_rules WHERE tenant_id=23
;
GO
