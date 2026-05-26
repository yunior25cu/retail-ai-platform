IF OBJECT_ID('gold.sp_refresh_all','P') IS NOT NULL DROP PROCEDURE gold.sp_refresh_all;
GO
CREATE PROCEDURE gold.sp_refresh_all
    @tenant_id BIGINT,
    @batch_id  UNIQUEIDENTIFIER = NULL OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    IF @batch_id IS NULL SET @batch_id = NEWID();

    DECLARE @master_log_id BIGINT;
    INSERT INTO gold.etl_batch_log (batch_id, tenant_id, step_name)
    VALUES (@batch_id, @tenant_id, N'sp_refresh_all');
    SET @master_log_id = SCOPE_IDENTITY();

    BEGIN TRY
        DECLARE @max_date    DATE = (SELECT MAX([date]) FROM gold.dim_date);
        DECLARE @needed_date DATE = DATEADD(DAY, 180, CAST(SYSUTCDATETIME() AS DATE));
        IF @max_date IS NULL OR @max_date < @needed_date
            EXEC gold.sp_populate_dim_date @from_date = '2020-01-01', @to_date = '2032-12-31';

        IF @tenant_id = 7
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM gold.dim_brand_mapping        WHERE tenant_id = 7)
                EXEC gold.sp_seed_brand_mapping_emp7;
            IF NOT EXISTS (SELECT 1 FROM gold.dim_store_classification WHERE tenant_id = 7)
                EXEC gold.sp_seed_store_classification_emp7;
            IF NOT EXISTS (SELECT 1 FROM gold.dim_business_rules       WHERE tenant_id = 7)
                EXEC gold.sp_seed_business_rules_emp7;
            IF NOT EXISTS (SELECT 1 FROM gold.dim_society_mapping      WHERE tenant_id = 7)
                EXEC gold.sp_seed_society_mapping_emp7;
        END;

        EXEC gold.sp_refresh_dim_category @tenant_id = @tenant_id, @batch_id = @batch_id;
        EXEC gold.sp_refresh_dim_store    @tenant_id = @tenant_id, @batch_id = @batch_id;
        EXEC gold.sp_refresh_dim_sku      @tenant_id = @tenant_id, @batch_id = @batch_id;

        DECLARE @from_week CHAR(8) = (
            SELECT TOP 1 dd.iso_year_week
            FROM gold.dim_date dd
            WHERE dd.[date] = (
                SELECT MIN(d.fecha_emision) FROM dbo.documento d
                 WHERE d.id_empresa = @tenant_id AND d.[delete] = 0 AND d.estado IN (1,2)
            )
            ORDER BY dd.[date]
        );
        DECLARE @to_week CHAR(8) = (
            SELECT iso_year_week FROM gold.dim_date
             WHERE [date] = CAST(SYSUTCDATETIME() AS DATE)
        );
        SET @from_week = ISNULL(@from_week, N'2020-W01');
        SET @to_week   = ISNULL(@to_week,   N'2030-W52');

        EXEC gold.sp_refresh_fact_sales_weekly
             @tenant_id = @tenant_id, @from_week = @from_week, @to_week = @to_week, @batch_id = @batch_id;
        EXEC gold.sp_refresh_fact_stock_movements
             @tenant_id = @tenant_id, @batch_id = @batch_id;
        EXEC gold.sp_refresh_fact_stock_weekly
             @tenant_id = @tenant_id, @from_week = @from_week, @to_week = @to_week, @batch_id = @batch_id;
        EXEC gold.sp_refresh_fact_transfers
             @tenant_id = @tenant_id, @batch_id = @batch_id;

        IF @tenant_id = 7
            EXEC gold.sp_seed_sales_plan_emp7;

        DECLARE @dup_skus INT, @sku_no_brand INT, @store_no_class INT,
                @neg_margin INT, @overcov INT, @missing_dim INT;

        SELECT @dup_skus = COUNT(*) FROM (
            SELECT sku_code FROM gold.dim_sku
             WHERE tenant_id = @tenant_id AND is_active = 1
             GROUP BY sku_code HAVING COUNT(*) > 1
        ) x;

        SELECT @sku_no_brand = COUNT(*) FROM gold.dim_sku
         WHERE tenant_id = @tenant_id AND is_active = 1 AND brand_id = 0;

        SELECT @store_no_class = COUNT(*) FROM gold.dim_store
         WHERE tenant_id = @tenant_id AND is_active = 1 AND block_AB = N'NO CLASIFICADO';

        SELECT @neg_margin = COUNT(*) FROM gold.fact_sales_weekly
         WHERE tenant_id = @tenant_id AND gross_margin_pct < 0;

        SELECT @overcov = COUNT(*) FROM gold.vw_sku_coverage_status
         WHERE tenant_id = @tenant_id AND days_coverage > 365;

        SELECT @missing_dim = COUNT(*) FROM gold.fact_sales_weekly f
         WHERE f.tenant_id = @tenant_id
           AND NOT EXISTS (
               SELECT 1 FROM gold.dim_sku ds
               WHERE ds.tenant_id = f.tenant_id AND ds.sku_id = f.sku_id
           );

        INSERT INTO gold.etl_data_quality_metrics
            (batch_id, tenant_id, table_name, metric_name, metric_value, severity)
        VALUES
            (@batch_id, @tenant_id, N'gold.dim_sku',                N'duplicate_sku_codes',              @dup_skus,
                CASE WHEN @dup_skus       > 0 THEN N'WARN'  ELSE N'INFO' END),
            (@batch_id, @tenant_id, N'gold.dim_sku',                N'skus_without_brand',               @sku_no_brand,
                CASE WHEN @sku_no_brand   > 0 THEN N'WARN'  ELSE N'INFO' END),
            (@batch_id, @tenant_id, N'gold.dim_store',              N'stores_without_classification',    @store_no_class,
                CASE WHEN @store_no_class > 0 THEN N'WARN'  ELSE N'INFO' END),
            (@batch_id, @tenant_id, N'gold.fact_sales_weekly',      N'sales_with_negative_margin_pct',   @neg_margin,
                CASE WHEN @neg_margin     > 0 THEN N'WARN'  ELSE N'INFO' END),
            (@batch_id, @tenant_id, N'gold.vw_sku_coverage_status', N'skus_with_coverage_over_365_days', @overcov,
                CASE WHEN @overcov        > 0 THEN N'WARN'  ELSE N'INFO' END),
            (@batch_id, @tenant_id, N'gold.fact_sales_weekly',      N'facts_with_missing_dim_join',      @missing_dim,
                CASE WHEN @missing_dim    > 0 THEN N'ERROR' ELSE N'INFO' END);

        UPDATE gold.etl_batch_log
           SET finished_at = SYSUTCDATETIME(),
               status      = N'SUCCESS',
               error_msg   = CONCAT(N'window=[', @from_week, N'..', @to_week, N']',
                                    N' dq_dups=',         @dup_skus,
                                    N' dq_no_brand=',     @sku_no_brand,
                                    N' dq_no_class=',     @store_no_class,
                                    N' dq_neg_margin=',   @neg_margin,
                                    N' dq_overcov=',      @overcov,
                                    N' dq_missing_dim=',  @missing_dim)
         WHERE id = @master_log_id;
    END TRY
    BEGIN CATCH
        UPDATE gold.etl_batch_log
           SET finished_at = SYSUTCDATETIME(),
               status      = N'FAILED',
               error_msg   = ERROR_MESSAGE()
         WHERE id = @master_log_id;
        THROW;
    END CATCH
END;
GO
